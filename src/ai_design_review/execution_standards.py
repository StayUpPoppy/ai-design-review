"""Shared execution-standard selection and versioned suggestion inputs."""
from __future__ import annotations

from copy import deepcopy

from .standard_selector import SUPPORTED_STANDARDS, select_standard

VERSION = "spring-standardization/v2"
MANUAL_SOURCES = {"human_selected", "manual"}
INPUT_FIELDS = (
    "material", "wire_diameter", "outer_diameter", "inner_diameter", "mean_diameter",
    "free_length", "total_coils", "active_coils", "support_coils", "end_type", "end_grinding",
    "pitch", "spring_rate", "controlled_diameter_field", "accuracy_grade",
    "diameter_accuracy_grade", "free_length_accuracy_grade", "load_accuracy_grade", "stiffness_accuracy_grade",
)


def resolve_selection(review: dict, *, include_references: bool = False) -> dict:
    current = review.get("standard_selection") or {}
    parameters = review.get("spring_parameters") or {}
    if current.get("selected_standard") and not current.get("selection_source"):
        return current
    manual = current.get("selection_source") in MANUAL_SOURCES
    selected = current.get("selected_standard") if manual else None
    if manual and selected not in SUPPORTED_STANDARDS:
        raise ValueError("请选择已接入的冷卷或热卷执行标准。")
    selection = select_standard(
        (review.get("drawing_summary") or {}).get("spring_type") or (review.get("spring_template") or {}).get("spring_type") or "unknown_spring",
        parameters, review.get("spring_features"), technical_requirements=review.get("technical_requirements"),
        include_references=include_references, manual_standard=selected,
    )
    metadata = selection.setdefault("metadata", {})
    original = (current.get("metadata") or {}).get("drawing_standard")
    metadata["drawing_standard"] = deepcopy(original if original is not None else parameters.get("standard_no") or {})
    if selection.get("selected_standard") == current.get("selected_standard"):
        for key in ("human_confirmed", "confirmed_at"):
            if key in current:
                selection[key] = current[key]
        if selection.get("human_confirmed"):
            selection["need_human_review"] = False
    review["standard_selection"] = selection
    return selection


def effective_grade(parameters: dict, specific_field: str = "accuracy_grade") -> str | None:
    from .accuracy_inference import grade
    general = parameters.get("accuracy_grade") or {}
    sources = general.get("source") or []
    sources = [sources] if isinstance(sources, str) else sources
    fields = ("accuracy_grade",) if MANUAL_SOURCES.intersection(sources) else (specific_field, "accuracy_grade")
    return next((value for field in fields if (value := grade((parameters.get(field) or {}).get("value")))), None)


def input_snapshot(review: dict) -> dict:
    parameters = review.get("spring_parameters") or {}
    values = {}
    for field in INPUT_FIELDS:
        item = parameters.get(field) or {}
        values[field] = {"value": item.get("value"), "unit": item.get("unit"), "stale": bool(item.get("derived_value_stale"))}
    values["wire_diameter"]["tolerance_upper"] = (parameters.get("wire_diameter") or {}).get("tolerance_upper")
    points = parameters.get("load_points") or []
    values["load_points"] = [{key: point.get(key) for key in ("load_point_id", "label", "force", "force_unit", "height", "height_unit")} for point in points]
    general = parameters.get("accuracy_grade") or {}
    sources = general.get("source") or []
    sources = [sources] if isinstance(sources, str) else sources
    return {"version": VERSION, "standard": (review.get("standard_selection") or {}).get("selected_standard"),
            "manual_grade": bool(MANUAL_SOURCES.intersection(sources)), "parameters": values}


def fingerprint(review: dict) -> str:
    from .accuracy_inference import _fingerprint
    return _fingerprint(input_snapshot(review))


def stamp_results(review: dict) -> None:
    review["standardization_context"] = {"version": VERSION, "input_fingerprint": fingerprint(review)}
    parameters = review.get("spring_parameters") or {}
    for result in review.get("standardization_results") or []:
        target = result.get("target_field", "")
        specific = "load_accuracy_grade" if target.startswith("load_points.") else {
            "outer_diameter": "diameter_accuracy_grade", "inner_diameter": "diameter_accuracy_grade",
            "free_length": "free_length_accuracy_grade", "spring_rate": "stiffness_accuracy_grade",
        }.get(target, "accuracy_grade")
        metadata = result.setdefault("metadata", {})
        metadata.update(review["standardization_context"])
        if target == "standard_no":
            metadata["value_kind"] = "reference_limit"
            result["suggested_value"] = review["standard_selection"].get("selected_standard")
        metadata["effective_grade"] = effective_grade(parameters, specific)
        if specific != "accuracy_grade":
            metadata["drawing_specific_grade"] = (parameters.get(specific) or {}).get("value")
    from .standardization_diagnostics import annotate_missing_roots
    annotate_missing_roots(review)


def invalidate_stale_results(review: dict) -> bool:
    results = review.get("standardization_results") or []
    if not results:
        return False
    context = review.get("standardization_context") or {}
    if context.get("version") == VERSION and context.get("input_fingerprint") == fingerprint(review):
        return False
    for result in results:
        result.update(status="stale", need_human_review=True)
    for turn in review.get("standardization_chat") or []:
        if turn.get("standardization_batch"):
            turn["standardization_batch"]["status"] = "stale"
    review["derived_parameters_stale"] = True
    return True
