from __future__ import annotations

from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .base import RecognitionEngine


class Werk24Engine(RecognitionEngine):
    """Werk24 adapter.

    The adapter returns the project's normalized candidate format while also
    keeping Werk24's raw payloads available for audit/debugging.
    """

    name = "werk24"

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        return self.extract_with_raw(file_path)["candidates"]

    def extract_with_raw(self, file_path: str | Path) -> dict[str, Any]:
        messages = self._read_messages(file_path)
        return messages_to_candidate_payload(messages)

    def _read_messages(self, file_path: str | Path) -> list[Any]:
        _ensure_werk24_credentials()

        try:
            from werk24 import AskBalloons, AskFeatures, AskMetaData, read_drawing_sync
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Werk24 SDK is not installed. Install requirements or run inside the project .venv."
            ) from exc

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(path)

        try:
            with path.open("rb") as drawing:
                return read_drawing_sync(
                    drawing,
                    [
                        AskMetaData(),
                        AskFeatures(),
                        AskBalloons(),
                    ],
                )
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(
                "Werk24 extraction failed. Check that W24TECHREAD_AUTH_TOKEN and "
                "W24TECHREAD_AUTH_REGION are configured, and that network access is available. "
                f"Underlying error: {detail}"
            ) from exc


def _ensure_werk24_credentials() -> None:
    try:
        from werk24.utils.license import find_license

        find_license()
    except Exception as exc:
        raise RuntimeError(
            "Werk24 credentials are missing or invalid. Run `python -m werk24.cli.werk24 init` "
            "or configure W24TECHREAD_AUTH_TOKEN and W24TECHREAD_AUTH_REGION before running "
            "extract-werk24 or review-werk24."
        ) from exc


def messages_to_candidate_payload(messages: Iterable[Any]) -> dict[str, Any]:
    raw_messages = [_message_to_dict(message) for message in messages]
    balloons = _collect_balloons(raw_messages)
    candidates: list[dict[str, Any]] = []

    for message in raw_messages:
        if not message.get("is_successful", False):
            continue
        payload = message.get("payload_dict") or {}
        page = message.get("page_number") or 1
        ask_type = _enum_text(payload.get("ask_type") or message.get("message_subtype"))

        if ask_type == "FEATURES":
            candidates.extend(_features_to_candidates(payload, balloons, page))
        elif ask_type == "META_DATA":
            candidates.extend(_metadata_to_candidates(payload, balloons, page))

    return {
        "engine": "werk24",
        "candidates": candidates,
        "raw_messages": raw_messages,
    }


def _message_to_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return {
            "request_id": str(message.get("request_id", "")),
            "message_type": _enum_text(message.get("message_type", "")),
            "message_subtype": _enum_text(message.get("message_subtype", "")),
            "page_number": message.get("page_number", 0) or 1,
            "is_successful": bool(message.get("is_successful", not message.get("exceptions"))),
            "exceptions": _dump_model(message.get("exceptions", [])),
            "payload_dict": _dump_model(message.get("payload_dict")),
            "payload_url": str(message.get("payload_url", "") or ""),
            "has_payload_bytes": bool(message.get("has_payload_bytes", False)),
        }

    if hasattr(message, "model_dump") and not hasattr(message, "payload_dict"):
        payload = _dump_model(message)
        ask_type = _enum_text(payload.get("ask_type"))
        return {
            "request_id": "",
            "message_type": "RESPONSE",
            "message_subtype": ask_type,
            "page_number": 1,
            "is_successful": True,
            "exceptions": [],
            "payload_dict": payload,
            "payload_url": "",
            "has_payload_bytes": False,
        }

    payload = _dump_model(getattr(message, "payload_dict", None))
    exceptions = _dump_model(getattr(message, "exceptions", []))
    return {
        "request_id": str(getattr(message, "request_id", "")),
        "message_type": _enum_text(getattr(message, "message_type", "")),
        "message_subtype": _enum_text(getattr(message, "message_subtype", "")),
        "page_number": getattr(message, "page_number", 0) or 1,
        "is_successful": bool(getattr(message, "is_successful", False)),
        "exceptions": exceptions,
        "payload_dict": payload,
        "payload_url": str(getattr(message, "payload_url", "") or ""),
        "has_payload_bytes": getattr(message, "payload_bytes", None) is not None,
    }


def _collect_balloons(raw_messages: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    balloons: dict[int, dict[str, Any]] = {}
    for message in raw_messages:
        payload = message.get("payload_dict") or {}
        if _enum_text(payload.get("ask_type") or message.get("message_subtype")) != "BALLOONS":
            continue
        for balloon in payload.get("balloons", []) or []:
            reference_id = balloon.get("reference_id")
            center = balloon.get("center")
            if reference_id is None or not center:
                continue
            balloons[int(reference_id)] = {
                "x": center[0],
                "y": center[1],
                "width": None,
                "height": None,
                "coordinate_type": "pixel",
            }
    return balloons


def _features_to_candidates(
    payload: dict[str, Any],
    balloons: dict[int, dict[str, Any]],
    page: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    feature_groups = [
        ("dimensions", "dimension"),
        ("bores", "bore"),
        ("chamfers", "chamfer"),
        ("radii", "radius"),
        ("roughnesses", "roughness"),
        ("threads", "thread"),
        ("gdnts", "gdnt"),
    ]

    for collection_name, feature_type in feature_groups:
        for feature in payload.get(collection_name, []) or []:
            candidates.append(_feature_to_candidate(feature, feature_type, balloons, page))
    return candidates


def _feature_to_candidate(
    feature: dict[str, Any],
    feature_type: str,
    balloons: dict[int, dict[str, Any]],
    page: int,
) -> dict[str, Any]:
    reference_id = feature.get("reference_id")
    size = _select_size(feature)
    tolerance = (size or {}).get("tolerance") or {}
    label = feature.get("label") or feature_type
    field = f"werk24_{feature_type}_{reference_id or len(label)}"

    return {
        "field": field,
        "feature_type": feature_type,
        "reference_id": reference_id,
        "value": _to_number((size or {}).get("value")),
        "unit": (size or {}).get("unit"),
        "size_type": _enum_text((size or {}).get("size_type")),
        "tolerance_upper": _to_number(tolerance.get("deviation_upper")),
        "tolerance_lower": _to_number(tolerance.get("deviation_lower")),
        "tolerance_grade": tolerance.get("tolerance_grade"),
        "quantity": feature.get("quantity"),
        "source": "werk24",
        "evidence": label,
        "confidence": _confidence(feature.get("confidence")),
        "page": page,
        "position": balloons.get(int(reference_id)) if reference_id is not None else None,
        "suggested_region": f"Werk24 {feature_type}",
        "raw": feature,
    }


def _metadata_to_candidates(
    payload: dict[str, Any],
    balloons: dict[int, dict[str, Any]],
    page: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for item in payload.get("designation", []) or []:
        candidates.append(_text_candidate("drawing_name", item, balloons, page, "Werk24 designation"))

    for identifier in payload.get("identifiers", []) or []:
        field = _identifier_field(identifier)
        candidates.append(_text_candidate(field, identifier, balloons, page, "Werk24 identifier"))

    for material_option in payload.get("material_options", []) or []:
        for material in material_option.get("material_combination", []) or []:
            value = material.get("designation") or material.get("raw_ocr")
            if not value:
                continue
            reference_id = material_option.get("reference_id")
            candidates.append(
                {
                    "field": "material",
                    "reference_id": reference_id,
                    "value": value,
                    "source": "werk24",
                    "evidence": material.get("raw_ocr") or value,
                    "confidence": 0.86,
                    "page": page,
                    "position": balloons.get(int(reference_id)) if reference_id is not None else None,
                    "suggested_region": "Werk24 material metadata",
                    "raw": material_option,
                }
            )

    for note in payload.get("notes", []) or []:
        reference_id = note.get("reference_id")
        label = note.get("label") or ""
        if not label:
            continue
        candidates.append(
            {
                "field": f"werk24_note_{reference_id or len(candidates)}",
                "feature_type": "note",
                "reference_id": reference_id,
                "value": label,
                "source": "werk24",
                "evidence": label,
                "confidence": _confidence(note.get("confidence")),
                "page": page,
                "position": balloons.get(int(reference_id)) if reference_id is not None else None,
                "suggested_region": "Werk24 note",
                "raw": note,
            }
        )

    return candidates


def _text_candidate(
    field: str,
    item: dict[str, Any],
    balloons: dict[int, dict[str, Any]],
    page: int,
    region: str,
) -> dict[str, Any]:
    reference_id = item.get("reference_id")
    return {
        "field": field,
        "reference_id": reference_id,
        "value": item.get("value"),
        "source": "werk24",
        "evidence": item.get("value", ""),
        "confidence": 0.86,
        "page": page,
        "position": balloons.get(int(reference_id)) if reference_id is not None else None,
        "suggested_region": region,
        "raw": item,
    }


def _identifier_field(identifier: dict[str, Any]) -> str:
    identifier_type = _enum_text(identifier.get("identifier_type")).lower()
    if "drawing" in identifier_type:
        return "drawing_no"
    if "revision" in identifier_type or "version" in identifier_type:
        return "version"
    if "part" in identifier_type:
        return "part_no"
    return f"werk24_identifier_{identifier.get('reference_id', 'unknown')}"


def _select_size(feature: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("size", "diameter", "depth", "width", "height", "length"):
        value = feature.get(key)
        if isinstance(value, dict) and "value" in value:
            return value
    return None


def _confidence(value: Any) -> float:
    if isinstance(value, dict):
        return float(value.get("score") or 0.86)
    if value is None:
        return 0.86
    return float(value)


def _dump_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _dump_model(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(k): _dump_model(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dump_model(item) for item in value]
    if isinstance(value, tuple):
        return [_dump_model(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _enum_text(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    text = str(value or "")
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.strip()


def _to_number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    number = float(value)
    if number.is_integer():
        return int(number)
    return number
