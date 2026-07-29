from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from ..end_conditions import normalize_end_grinding, normalize_end_type
from .base import RecognitionEngine
from ..llm_standardization import LLM_STANDARDIZATION_FIELD
from ..preprocessing import IMAGE_EXTENSIONS, render_pdf_with_pdftoppm
from ..spring_templates import FIELD_LABELS, SPRING_TEMPLATES, SPRING_TYPE_UNKNOWN, template_for


DEFAULT_QWEN_MODEL = "qwen3.7-plus"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_SOURCE = "qwen_vision"


class QwenVisionError(RuntimeError):
    """Raised when Qwen vision cannot return parseable recognition JSON."""


class QwenVisionEngine(RecognitionEngine):
    """Qwen3.7 multimodal direct recognizer for spring drawings."""

    name = QWEN_SOURCE

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        work_dir: str | Path | None = None,
        max_pages: int | None = None,
    ):
        self.api_key = api_key or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self.model = model or os.getenv("QWEN_MODEL") or DEFAULT_QWEN_MODEL
        self.base_url = (base_url or os.getenv("QWEN_BASE_URL") or DEFAULT_QWEN_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(os.getenv("QWEN_TIMEOUT_SECONDS", "90"))
        self.work_dir = Path(work_dir) if work_dir else None
        self.max_pages = max_pages or int(os.getenv("QWEN_MAX_PAGES", "3"))

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        return self.extract_with_raw(file_path)["candidates"]

    def extract_with_raw(
        self,
        file_path: str | Path,
        image_paths: list[str | Path] | None = None,
    ) -> dict[str, Any]:
        if not _configured(self.api_key):
            raise QwenVisionError("Qwen API key is not configured. Set QWEN_API_KEY or DASHSCOPE_API_KEY.")

        path = Path(file_path)
        prepared_images = [Path(item) for item in image_paths] if image_paths else self._prepare_images(path)
        prepared_images = prepared_images[: self.max_pages]
        if not prepared_images:
            raise QwenVisionError("No rendered page images are available for Qwen vision recognition.")

        started = time.monotonic()
        raw_response = self._call_qwen(prepared_images)
        content = _message_content(raw_response)
        parsed = parse_qwen_json(content)
        candidates = qwen_payload_to_candidates(parsed)
        return {
            "engine": self.name,
            "model": self.model,
            "image_paths": [str(item) for item in prepared_images],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "parsed": parsed,
            "candidates": candidates,
            "raw": raw_response,
        }

    def _prepare_images(self, file_path: Path) -> list[Path]:
        suffix = file_path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            return [file_path]
        if suffix != ".pdf":
            raise QwenVisionError(f"Qwen vision only supports PDF or image input: {suffix}")
        output_dir = self.work_dir or file_path.parent / f"{file_path.stem}_qwen_pages"
        output_dir.mkdir(parents=True, exist_ok=True)
        return [
            Path(item)
            for item in render_pdf_with_pdftoppm(
                file_path,
                output_dir,
                prefix="qwen_page",
                dpi=int(os.getenv("QWEN_RENDER_DPI", "220")),
            )
        ]

    def _call_qwen(self, image_paths: list[Path]) -> dict[str, Any]:
        import httpx

        endpoint = _chat_completions_endpoint(self.base_url)
        content: list[dict[str, Any]] = [{"type": "text", "text": QWEN_SYSTEM_PROMPT}]
        for image_path in image_paths:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_data_url(image_path),
                    },
                }
            )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code in {400, 422} and "response_format" in response.text:
                payload.pop("response_format", None)
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            response.raise_for_status()
            return response.json()


QWEN_SYSTEM_PROMPT = """你是弹簧工程图纸识别助手。请阅读上传的 PDF 页面图片或图纸图片，只输出严格 JSON，不要输出 Markdown。

任务：
1. 判断弹簧类型，只能使用 compression_spring、torsion_spring、extension_spring、retaining_ring、unknown_spring。
2. 提取图纸名称、图号、版本、材料。
3. 按弹簧类型提取尺寸字段。字段名必须使用英文 key，前端会用中文标签显示；不要自造 key。
   - 通用：material、standard_no、accuracy_grade、wire_diameter、outer_diameter、inner_diameter、mean_diameter、free_length、body_length、total_coils、active_coils、handedness、pitch。
   - standard_no 只能填写弹簧产品适用的通用技术/公差标准，例如 GB/T 1239.2、GB/T 23934；材料或钢丝牌号标准（例如“弹簧钢丝 GB/T 4357-2009”）只能放在 material，绝不能填入 standard_no。
   - 压缩弹簧：diameter_accuracy_grade、free_length_accuracy_grade、load_accuracy_grade、stiffness_accuracy_grade、controlled_diameter_field、solid_height、end_coils、support_coils、end_type、end_grinding、spring_rate、perpendicularity、straightness、permanent_set_limit，可提取 load_points。
   - 扭转弹簧：coil_body_length、arm_length、short_arm_length、long_arm_length、leg1_length、leg2_length、free_angle、working_angle、leg1_angle、leg2_angle、bend_radius、leg_end_type、mandrel_diameter、torque。
   - 拉伸弹簧：hook_type、hook_outer_diameter、hook_inner_diameter、hook_gap、hook1_type、hook2_type、hook1_length、hook2_length、hook1_outer_diameter、hook2_outer_diameter、hook1_inner_diameter、hook2_inner_diameter、hook1_opening、hook2_opening、hook_orientation、center_to_center_length、initial_tension，可提取 load_points。
   - 卡簧/挡圈：ring_type、thickness、free_diameter、opening_width、gap_width、notch_depth、groove_diameter、groove_width、lug_hole_diameter、lug_center_distance、opening_angle、section_width、section_height、chamfer、corner_radius。
   - 端面磨削 end_grinding：只有图纸文字明确写“不磨/未磨”时才填“两端不磨削”；只有文字明确写“磨平/磨削”，或两端面有明确关联的表面粗糙度/加工符号且端面画为平整时才填“两端磨削”。不得仅因弹簧示意图看似开口、或没有文字标注，就推断为“不磨”；无法确定时不要输出该字段。
   - 端部形式 end_type：只有图纸文字明确写“并紧/闭口”时才填“两端并紧”；明确写“不并紧/开口”时才填“两端不并紧”。端部形式与端面磨削是独立字段，无法确定时不要输出。
   - 表面粗糙度符号、加工符号或小三角旁的数值（例如 Ra 12.5、▽ 12.5）属于技术要求，绝不能填入 outer_diameter、inner_diameter、mean_diameter、free_length、body_length、wire_diameter 或 load_points。
   - 对圆柱压缩弹簧：outer_diameter 必须来自直径尺寸线、直径符号或紧邻的一侧公差；free_length 必须来自两端之间的轴向总长度尺寸线；H1/H2 只属于 load_points 的试验高度。没有足够定位依据时省略字段并标记 need_human_review=true。
4. 提取动态工艺要求：surface、hardness、heat_treatment、salt_spray、environmental、lifetime、process、other。表面处理、硬度、热处理、盐雾等不要放进 parameters，放进 technical_requirements。
5. 对压缩弹簧，额外判断是否属于圆柱螺旋压缩弹簧，并输出 spring_features：
   - spring_family 只能为 helical、disc、wave、rubber、gas、unknown。
   - spring_shape 只能为 cylindrical、conical、barrel、hourglass、unknown。
   - manufacturing_method 只能为 cold_coiled、hot_coiled、unknown。图纸写 GB/T 1239.2、冷卷、冷绕、冷成形时倾向 cold_coiled；写 GB/T 23934、热卷、热绕、热成形时倾向 hot_coiled；没有依据时必须 unknown。
   - wire_section 只能为 round、rectangular、square、unknown。
   - pitch_type 只能为 constant、variable、unknown。
6. 对压缩弹簧，输出 standard_selection_inference：推荐标准、制造方式、置信度、证据、原因、是否需要人工确认。只能在有标准号、工艺关键词或明显结构证据时推荐；证据不足时 selected_standard 为空或 unknown，并 need_human_review=true。
7. 对压缩弹簧，只识别图纸已写明的标准号、等级、端部形式、刚度、垂直度、直线度等；不要计算标准公差，标准公差由后端规则表计算。
8. 不确定或识别不到的字段不要猜；可以留空或省略，并标记 need_human_review=true。只根据图纸可见文字、尺寸线和表格内容输出。

JSON 结构：
{
  "spring_type": {"value": "compression_spring", "label": "压缩弹簧", "confidence": 0.0, "evidence": "", "need_human_review": true},
  "drawing_summary": {"drawing_name": "", "drawing_no": "", "version": ""},
  "parameters": {
    "material": {"value": "", "confidence": 0.0, "evidence": "", "need_human_review": true},
    "wire_diameter": {"value": null, "unit": "mm", "tolerance_upper": null, "tolerance_lower": null, "confidence": 0.0, "evidence": "", "need_human_review": true}
  },
  "spring_features": {
    "spring_family": {"value": "helical", "confidence": 0.0, "evidence": "", "need_human_review": true},
    "spring_shape": {"value": "cylindrical", "confidence": 0.0, "evidence": "", "need_human_review": true},
    "manufacturing_method": {"value": "unknown", "confidence": 0.0, "evidence": "", "need_human_review": true},
    "wire_section": {"value": "round", "confidence": 0.0, "evidence": "", "need_human_review": true},
    "pitch_type": {"value": "constant", "confidence": 0.0, "evidence": "", "need_human_review": true}
  },
  "standard_selection_inference": {"selected_standard": "", "manufacturing_method": "unknown", "confidence": 0.0, "evidence": [], "reason": "", "need_human_review": true},
  "load_points": [
    {"label": "F1", "height": null, "height_unit": "mm", "force": null, "force_unit": "N", "force_tolerance_percent": null, "load_tolerance_upper": null, "load_tolerance_lower": null, "load_tolerance_percent": null, "test_height_type": "", "reference_only": false, "confidence": 0.0, "evidence": "", "need_human_review": true}
  ],
  "technical_requirements": [
    {"type": "surface", "content": "", "confidence": 0.0, "evidence": "", "need_human_review": true}
  ],
  "notes": ""
}
"""


def qwen_payload_to_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    spring_type = _spring_type_payload(payload.get("spring_type"))
    if spring_type:
        label = spring_type.get("label") or _spring_label(spring_type.get("value"))
        candidates.append(
            _candidate(
                "spring_type",
                label,
                spring_type,
                unit=None,
                default_confidence=0.82,
                suggested_region="Qwen spring type classification",
            )
        )
        candidates.append(
            {
                "field": "document_text_qwen",
                "feature_type": "note",
                "value": f"Qwen识别类型：{label}。{spring_type.get('evidence', '')}",
                "source": QWEN_SOURCE,
                "evidence": spring_type.get("evidence", label),
                "confidence": _confidence(spring_type, 0.76),
                "page": 1,
                "position": None,
                "suggested_region": "Qwen spring type classification",
            }
        )

    summary = payload.get("drawing_summary") if isinstance(payload.get("drawing_summary"), dict) else {}
    for field in ("drawing_name", "drawing_no", "version"):
        value = summary.get(field)
        if value not in (None, ""):
            candidates.append(
                _candidate(
                    field,
                    value,
                    {"confidence": 0.82, "evidence": str(value)},
                    suggested_region="Qwen drawing summary",
                )
            )

    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    for field, item in parameters.items():
        candidates.extend(_parameter_candidate(field, item))

    spring_features = payload.get("spring_features") if isinstance(payload.get("spring_features"), dict) else {}
    for field in ("spring_family", "spring_shape", "manufacturing_method", "wire_section", "pitch_type"):
        candidates.extend(_parameter_candidate(field, spring_features.get(field)))

    standard_inference = payload.get("standard_selection_inference") or payload.get("standard_selection")
    if isinstance(standard_inference, dict):
        candidates.append(
            _candidate(
                "standard_selection_inference",
                dict(standard_inference),
                standard_inference,
                suggested_region="Qwen cold/hot coiled standard inference",
            )
        )

    standardization_results = payload.get("standardization_results") or payload.get(LLM_STANDARDIZATION_FIELD)
    if isinstance(standardization_results, (list, dict)):
        candidates.append(
            _candidate(
                LLM_STANDARDIZATION_FIELD,
                standardization_results,
                {
                    "confidence": payload.get("standardization_confidence", 0.72),
                    "evidence": f"LLM standardization results: {len(standardization_results) if isinstance(standardization_results, list) else 1} item(s)",
                    "need_human_review": True,
                },
                suggested_region="LLM/RAG standardization JSON",
            )
        )

    for item in payload.get("load_points") or []:
        if not isinstance(item, dict):
            continue
        value = {
            "label": item.get("label") or f"F{len([c for c in candidates if c.get('field') == 'load_point']) + 1}",
            "height": _numeric_or_none(item.get("height")),
            "height_unit": item.get("height_unit") or "mm",
            "force": _numeric_or_none(item.get("force")),
            "force_unit": item.get("force_unit") or "N",
            "force_tolerance_percent": _numeric_or_none(item.get("force_tolerance_percent")),
            "load_tolerance_upper": _numeric_or_none(item.get("load_tolerance_upper")),
            "load_tolerance_lower": _numeric_or_none(item.get("load_tolerance_lower")),
            "load_tolerance_percent": _numeric_or_none(item.get("load_tolerance_percent")),
            "test_height_type": item.get("test_height_type") or "",
            "reference_only": bool(item.get("reference_only", False)),
        }
        if value["height"] is None and value["force"] is None:
            continue
        candidates.append(
            _candidate(
                "load_point",
                value,
                item,
                suggested_region="Qwen load point recognition",
            )
        )

    for item in payload.get("technical_requirements") or []:
        if not isinstance(item, dict):
            continue
        field = _technical_type_to_field(str(item.get("type") or "other"))
        content = item.get("content")
        if content in (None, ""):
            continue
        candidates.append(
            _candidate(
                field,
                content,
                item,
                suggested_region="Qwen technical requirement recognition",
            )
        )

    notes = str(payload.get("notes") or "").strip()
    if notes:
        candidates.append(
            {
                "field": "document_text_qwen_notes",
                "feature_type": "note",
                "value": notes[:4000],
                "source": QWEN_SOURCE,
                "evidence": notes[:4000],
                "confidence": 0.68,
                "page": 1,
                "position": None,
                "suggested_region": "Qwen notes",
            }
        )
    return candidates


def parse_qwen_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    if not text:
        raise QwenVisionError("Qwen response content is empty.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise QwenVisionError("Qwen response does not contain JSON.")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise QwenVisionError("Qwen JSON response must be an object.")
    return payload


def qwen_runtime_status() -> dict[str, Any]:
    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    return {
        "status": "configured" if _configured(api_key) else "not_configured",
        "model": os.getenv("QWEN_MODEL") or DEFAULT_QWEN_MODEL,
        "base_url": os.getenv("QWEN_BASE_URL") or DEFAULT_QWEN_BASE_URL,
    }


def _parameter_candidate(field: str, item: Any) -> list[dict[str, Any]]:
    if item is None:
        return []
    if isinstance(item, dict):
        value = item.get("value")
        if value in (None, ""):
            return []
        normalized = _normalize_parameter_value(field, value)
        return [_candidate(field, normalized, item, unit=item.get("unit"))] if normalized not in (None, "") else []
    if item == "":
        return []
    normalized = _normalize_parameter_value(field, item)
    return [_candidate(field, normalized, {"confidence": 0.72, "evidence": str(item)})] if normalized not in (None, "") else []


def _normalize_parameter_value(field: str, value: Any) -> Any:
    if field == "end_grinding":
        return normalize_end_grinding(value)
    if field == "end_type":
        return normalize_end_type(value)
    return _normalize_value(value)


def _candidate(
    field: str,
    value: Any,
    item: dict[str, Any] | None,
    unit: str | None = None,
    default_confidence: float = 0.78,
    suggested_region: str = "Qwen vision recognition",
) -> dict[str, Any]:
    item = item or {}
    confidence = _confidence(item, default_confidence)
    if bool(item.get("need_human_review", False)):
        confidence = min(confidence, 0.68)
    return {
        "field": field,
        "feature_type": "dimension" if field in FIELD_LABELS else "note",
        "value": value,
        "unit": unit if unit is not None else item.get("unit"),
        "tolerance_upper": item.get("tolerance_upper"),
        "tolerance_lower": item.get("tolerance_lower"),
        "source": QWEN_SOURCE,
        "evidence": str(item.get("evidence") or value),
        "confidence": confidence,
        "page": int(item.get("page", 1) or 1),
        "position": item.get("position"),
        "suggested_region": item.get("suggested_region") or suggested_region,
    }


def _spring_type_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        spring_type = str(value.get("value") or "").strip()
        if not spring_type:
            return None
        return value
    if isinstance(value, str) and value.strip():
        return {"value": value.strip(), "label": _spring_label(value.strip()), "confidence": 0.76, "evidence": value.strip()}
    return None


def _spring_label(value: Any) -> str:
    text = str(value or "").strip()
    if text in SPRING_TEMPLATES:
        return template_for(text)["label"]
    lowered = text.lower()
    mapping = {
        "compression": "压缩弹簧",
        "torsion": "扭转弹簧",
        "extension": "拉伸弹簧",
        "retaining": "卡簧/挡圈",
        "unknown": "未知弹簧",
    }
    for key, label in mapping.items():
        if key in lowered:
            return label
    return text or template_for(SPRING_TYPE_UNKNOWN)["label"]


def _technical_type_to_field(kind: str) -> str:
    normalized = kind.strip().lower()
    mapping = {
        "surface": "surface_requirement",
        "surface_requirement": "surface_requirement",
        "表面处理": "surface_requirement",
        "hardness": "hardness",
        "heat": "heat_treatment",
        "heat_treatment": "heat_treatment",
        "salt": "salt_spray",
        "salt_spray": "salt_spray",
        "environmental": "environmental",
        "lifetime": "lifetime_test",
        "life": "lifetime_test",
        "process": "process_requirement",
        "other": "other_requirement",
    }
    return mapping.get(normalized, mapping.get(kind.strip(), "other_requirement"))


def _confidence(item: dict[str, Any], default: float) -> float:
    try:
        value = float(item.get("confidence", default))
    except Exception:
        value = default
    return round(max(0.0, min(0.99, value)), 3)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        number = _numeric_or_none(stripped)
        return number if number is not None and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", stripped) else stripped
    return value


def _numeric_or_none(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _message_content(raw_response: dict[str, Any]) -> Any:
    choices = raw_response.get("choices") or []
    if not choices:
        raise QwenVisionError("Qwen response does not contain choices.")
    message = choices[0].get("message") or {}
    return message.get("content")


def _chat_completions_endpoint(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url.rstrip('/')}/chat/completions"


def _image_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(suffix, "image/png")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _configured(value: str | None) -> bool:
    return bool(value and value.strip() and "replace-with" not in value)
