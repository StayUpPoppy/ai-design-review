from __future__ import annotations

from typing import Any

from .balloons import generate_balloons
from .fusion import fuse_candidates
from .preprocessing import probe_file
from .rules import REQUIRED_FIELDS, determine_erp_ready, overall_status, run_rule_checks, should_require_human_review
from .semantic import apply_spring_semantic_mapping


TECHNICAL_FIELD_TYPES = {
    "heat_treatment": "heat_treatment",
    "surface_requirement": "surface",
    "salt_spray": "salt_spray",
    "lifetime_test": "lifetime",
    "environmental": "environmental",
}


class DrawingReviewWorkflow:
    """Deterministic workflow mirroring the future LangGraph nodes."""

    def __init__(self, factory_rules: dict[str, Any]):
        self.factory_rules = factory_rules

    def run(self, file_path: str | None, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        file_info = probe_file(file_path) if file_path else {"path": None, "kind": "unknown", "is_scanned_like": None}
        candidates = apply_spring_semantic_mapping(candidates)
        fused = fuse_candidates(candidates)
        spring_parameters = self._build_spring_parameters(fused["fields"], fused["load_points"])
        technical_requirements = self._build_technical_requirements(fused["fields"])
        review_results = run_rule_checks(
            spring_parameters,
            technical_requirements,
            file_info,
            self.factory_rules,
        )
        human_review_required = should_require_human_review(spring_parameters, review_results)
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
                "spring_type": "compression_spring",
                "material": _value(fused["fields"], "material", ""),
                "unit": "mm",
                "overall_status": status,
                "summary": _summary(status, human_review_required, erp_ready),
            },
            "file_info": file_info,
            "spring_parameters": spring_parameters,
            "technical_requirements": technical_requirements,
            "review_results": review_results,
            "balloons": balloons,
            "conflicts": fused["conflicts"],
            "missing_fields": _missing_fields(spring_parameters),
            "human_review_required": human_review_required,
            "erp_ready": erp_ready,
            "erp_block_reason": erp_block_reason,
        }

    def _build_spring_parameters(
        self,
        fields: dict[str, dict[str, Any]],
        load_points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "material": self._param(fields, "material"),
            "wire_diameter": self._param(fields, "wire_diameter", "mm"),
            "outer_diameter": self._param(fields, "outer_diameter", "mm"),
            "inner_diameter": self._param(fields, "inner_diameter", "mm"),
            "mean_diameter": self._param(fields, "mean_diameter", "mm"),
            "free_length": self._param(fields, "free_length", "mm"),
            "total_coils": self._param(fields, "total_coils", "turns"),
            "active_coils": self._param(fields, "active_coils", "turns"),
            "handedness": self._param(fields, "handedness"),
            "pitch": self._param(fields, "pitch", "mm"),
            "end_type": self._param(fields, "end_type"),
            "load_points": [self._load_point(item) for item in load_points],
        }

    def _build_technical_requirements(self, fields: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        requirements = []
        for field, requirement_type in TECHNICAL_FIELD_TYPES.items():
            item = fields.get(field)
            if not item:
                continue
            requirements.append(
                {
                    "type": requirement_type,
                    "content": item.get("value", ""),
                    "source": item.get("source", []),
                    "evidence": item.get("evidence", ""),
                    "confidence": item.get("confidence", 0),
                    "need_human_review": item.get("need_human_review", True),
                    "page": item.get("page", 1),
                    "position": item.get("position"),
                    "suggested_region": item.get("suggested_region", ""),
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


def _missing_fields(spring_parameters: dict[str, Any]) -> list[str]:
    missing = []
    for field in REQUIRED_FIELDS:
        value = spring_parameters.get(field, {})
        if isinstance(value, dict) and value.get("value") in (None, ""):
            missing.append(field)
    if not spring_parameters.get("load_points"):
        missing.append("load_points")
    return missing


def _summary(status: str, human_review_required: bool, erp_ready: bool) -> str:
    if erp_ready:
        return "图纸关键字段已通过自动审查，可进入 ERP 前置流程。"
    if human_review_required:
        return f"当前审查状态为 {status}，存在需要人工确认的字段，暂不允许自动进入 ERP。"
    return f"当前审查状态为 {status}，需根据规则结果处理后再放行。"
