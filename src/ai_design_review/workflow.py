from __future__ import annotations

from typing import Any

from .balloons import generate_balloons
from .fusion import fuse_candidates
from .preprocessing import probe_file
from .rules import REQUIRED_FIELDS, determine_erp_ready, overall_status, run_rule_checks, should_require_human_review
from .semantic import apply_spring_semantic_mapping
from .spring_templates import (
    classify_spring_type,
    field_default_unit,
    required_field_keys,
    template_field_keys,
    template_for,
)
from .surface_terms import normalize_surface_requirement


TECHNICAL_FIELD_TYPES = {
    "heat_treatment": "heat_treatment",
    "surface_requirement": "surface",
    "hardness": "hardness",
    "salt_spray": "salt_spray",
    "lifetime_test": "lifetime",
    "environmental": "environmental",
    "process_requirement": "process",
    "other_requirement": "other",
}


class DrawingReviewWorkflow:
    """Deterministic workflow mirroring the future LangGraph nodes."""

    def __init__(self, factory_rules: dict[str, Any]):
        self.factory_rules = factory_rules

    def run(self, file_path: str | None, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        file_info = probe_file(file_path) if file_path else {"path": None, "kind": "unknown", "is_scanned_like": None}
        candidates = [*_file_text_candidates(file_info), *candidates]
        dimension_evidence = _dimension_evidence(candidates)
        candidates = apply_spring_semantic_mapping(candidates)
        fused = fuse_candidates(candidates)
        classification = classify_spring_type(candidates, file_info)
        spring_type = classification["spring_type"]
        spring_template = template_for(spring_type)
        spring_parameters = self._build_spring_parameters(fused["fields"], fused["load_points"], spring_type)
        technical_requirements = self._build_technical_requirements(fused["fields"])
        review_results = run_rule_checks(
            spring_parameters,
            technical_requirements,
            file_info,
            self.factory_rules,
            spring_type=spring_type,
            required_fields=required_field_keys(spring_type),
        )
        human_review_required = should_require_human_review(spring_parameters, review_results)
        if any(item.get("need_human_review") for item in technical_requirements):
            human_review_required = True
        if classification.get("need_human_review"):
            human_review_required = True
        erp_ready, erp_block_reason = determine_erp_ready(
            review_results,
            human_review_required,
            self.factory_rules,
        )
        balloons = generate_balloons(spring_parameters, technical_requirements, review_results)
        status = overall_status(review_results)

        return {
            "drawing_summary": {
                "drawing_name": _value(fused["fields"], "drawing_name", ""),
                "drawing_no": _value(fused["fields"], "drawing_no", ""),
                "version": _value(fused["fields"], "version", ""),
                "spring_type": spring_type,
                "spring_type_label": spring_template["label"],
                "spring_type_confidence": classification["confidence"],
                "material": _value(fused["fields"], "material", ""),
                "unit": "mm",
                "overall_status": status,
                "summary": _summary(status, human_review_required, erp_ready),
            },
            "spring_type_detection": classification,
            "spring_template": spring_template,
            "file_info": file_info,
            "spring_parameters": spring_parameters,
            "technical_requirements": technical_requirements,
            "dimension_evidence": dimension_evidence,
            "review_results": review_results,
            "balloons": balloons,
            "conflicts": fused["conflicts"],
            "missing_fields": _missing_fields(spring_parameters, required_field_keys(spring_type)),
            "human_review_required": human_review_required,
            "erp_ready": erp_ready,
            "erp_block_reason": erp_block_reason,
        }

    def _build_spring_parameters(
        self,
        fields: dict[str, dict[str, Any]],
        load_points: list[dict[str, Any]],
        spring_type: str,
    ) -> dict[str, Any]:
        parameters = {
            field: self._param(fields, field, field_default_unit(spring_type, field))
            for field in template_field_keys(spring_type)
        }
        parameters["load_points"] = [self._load_point(item) for item in load_points]
        parameters["torque_points"] = []
        return parameters

    def _build_technical_requirements(self, fields: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        requirements = []
        for field, requirement_type in TECHNICAL_FIELD_TYPES.items():
            item = fields.get(field)
            if not item:
                continue
            content = item.get("value", "")
            extra: dict[str, Any] = {}
            need_human_review = item.get("need_human_review", True)
            if requirement_type == "surface":
                normalized = normalize_surface_requirement(content)
                content = normalized["content"]
                extra = {
                    "raw_content": normalized["raw_content"],
                    "standard_content": normalized["standard_content"],
                    "normalization_status": normalized["normalization_status"],
                    "normalization_confidence": normalized["normalization_confidence"],
                    "standard_candidates": normalized["standard_candidates"],
                }
                need_human_review = bool(need_human_review or normalized["need_human_review"])
            requirements.append(
                {
                    "type": requirement_type,
                    "content": content,
                    "source": item.get("source", []),
                    "evidence": item.get("evidence", ""),
                    "confidence": item.get("confidence", 0),
                    "need_human_review": need_human_review,
                    "page": item.get("page", 1),
                    "position": item.get("position"),
                    "suggested_region": item.get("suggested_region", ""),
                    **extra,
                }
            )
        return requirements

    def _param(self, fields: dict[str, dict[str, Any]], field: str, default_unit: str | None = None) -> dict[str, Any]:
        item = fields.get(field, {})
        return {
            "value": item.get("value"),
            "unit": item.get("unit") or default_unit,
            "tolerance_upper": item.get("tolerance_upper"),
            "tolerance_lower": item.get("tolerance_lower"),
            "source": item.get("source", []),
            "evidence": item.get("evidence", ""),
            "confidence": item.get("confidence", 0),
            "need_human_review": item.get("need_human_review", True),
            "page": item.get("page", 1),
            "position": item.get("position"),
            "suggested_region": item.get("suggested_region", ""),
        }

    def _load_point(self, item: dict[str, Any]) -> dict[str, Any]:
        value = item.get("value", {})
        return {
            "label": value.get("label"),
            "height": value.get("height"),
            "height_unit": value.get("height_unit", "mm"),
            "force": value.get("force"),
            "force_unit": value.get("force_unit", "N"),
            "force_tolerance_percent": value.get("force_tolerance_percent"),
            "reference_only": value.get("reference_only", False),
            "source": item.get("source", []),
            "evidence": item.get("evidence", ""),
            "confidence": item.get("confidence", 0),
            "need_human_review": item.get("need_human_review", True),
            "page": item.get("page", 1),
            "position": item.get("position"),
            "suggested_region": item.get("suggested_region", ""),
        }


def _value(fields: dict[str, dict[str, Any]], field: str, default: Any = None) -> Any:
    return fields.get(field, {}).get("value", default)


def _file_text_candidates(file_info: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(file_info.get("pdf_text") or "").strip()
    if not text:
        return []
    return [
        {
            "field": "document_text_pdf",
            "feature_type": "note",
            "value": text[:12000],
            "source": "pdf_text_layer",
            "evidence": text[:12000],
            "confidence": 0.74,
            "page": 1,
            "position": None,
            "suggested_region": "PDF text layer",
        }
    ]


def _dimension_evidence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = []
    for candidate in candidates:
        if candidate.get("feature_type") != "dimension_evidence":
            continue
        value = candidate.get("value")
        if isinstance(value, dict):
            item = dict(value)
        else:
            item = {
                "kind": candidate.get("field", "dimension_evidence"),
                "value": value,
            }
        item.setdefault("source", candidate.get("source", "geometry"))
        item.setdefault("page", candidate.get("page", 1))
        item.setdefault("position", candidate.get("position"))
        item.setdefault("confidence", candidate.get("confidence", 0))
        item.setdefault("suggested_region", candidate.get("suggested_region", "Geometry evidence"))
        evidence.append(item)
    return evidence


def _missing_fields(spring_parameters: dict[str, Any], required_fields: list[str] | None = None) -> list[str]:
    missing = []
    for field in required_fields or REQUIRED_FIELDS:
        value = spring_parameters.get(field, {})
        if isinstance(value, dict) and value.get("value") in (None, ""):
            missing.append(field)
    if "load_points" in (required_fields or []) and not spring_parameters.get("load_points"):
        missing.append("load_points")
    return missing


def _summary(status: str, human_review_required: bool, erp_ready: bool) -> str:
    if erp_ready:
        return "图纸关键字段已通过自动审查，可进入 ERP 前置流程。"
    if human_review_required:
        return f"当前审查状态为 {status}，存在需要人工确认的字段，暂不允许自动进入 ERP。"
    return f"当前审查状态为 {status}，需根据规则结果处理后再放行。"
