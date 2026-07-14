from __future__ import annotations

from typing import Any

from .balloons import generate_balloons
from .dimension_roles import apply_compression_dimension_role_ranking
from .fusion import fuse_candidates
from .llm_standardization import LLM_STANDARDIZATION_FIELD, normalize_llm_standardization_results
from .material_terms import normalize_material
from .preprocessing import probe_file
from .rules import REQUIRED_FIELDS, determine_erp_ready, overall_status, run_rule_checks, should_require_human_review
from .semantic import apply_spring_semantic_mapping
from .standardizers import standardize_spring
from .standardizers.coil_counts import apply_company_simple_active_coils
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

SPRING_FEATURE_FIELDS = (
    "spring_family",
    "spring_shape",
    "manufacturing_method",
    "wire_section",
    "pitch_type",
)

ACCURACY_GRADE_FIELDS = (
    "accuracy_grade",
    "diameter_accuracy_grade",
    "free_length_accuracy_grade",
    "load_accuracy_grade",
    "stiffness_accuracy_grade",
)


class DrawingReviewWorkflow:
    """Deterministic workflow mirroring the future LangGraph nodes."""

    def __init__(self, factory_rules: dict[str, Any]):
        self.factory_rules = factory_rules

    def run(
        self,
        file_path: str | None,
        candidates: list[dict[str, Any]],
        *,
        run_standardization: bool = True,
    ) -> dict[str, Any]:
        file_info = probe_file(file_path) if file_path else {"path": None, "kind": "unknown", "is_scanned_like": None}
        candidates = [*_file_text_candidates(file_info), *candidates]
        dimension_evidence = _dimension_evidence(candidates)
        candidates = apply_spring_semantic_mapping(candidates)
        candidates = apply_compression_dimension_role_ranking(candidates)
        fused = fuse_candidates(candidates)
        classification = classify_spring_type(candidates, file_info)
        spring_type = classification["spring_type"]
        spring_template = template_for(spring_type)
        spring_parameters = self._build_spring_parameters(fused["fields"], fused["load_points"], spring_type)
        self._apply_company_default_accuracy(spring_parameters, spring_type)
        apply_company_simple_active_coils(spring_type, spring_parameters)
        spring_features = self._build_spring_features(fused["fields"], spring_type)
        technical_requirements = self._build_technical_requirements(fused["fields"])
        if run_standardization:
            standardization = standardize_spring(
                spring_type,
                spring_parameters,
                spring_features=spring_features,
                standard_selection_inference=fused["fields"].get("standard_selection_inference"),
                technical_requirements=technical_requirements,
            )
            derived_parameters = standardization["derived_parameters"]
            standardization_results = standardization["standardization_results"]
            standard_selection = standardization["standard_selection"]
            llm_standardization = normalize_llm_standardization_results(
                fused["fields"].get(LLM_STANDARDIZATION_FIELD),
                spring_type=spring_type,
                spring_parameters=spring_parameters,
                standard_selection=standard_selection,
            )
            if llm_standardization["standardization_results"]:
                standardization_results = [
                    *standardization_results,
                    *llm_standardization["standardization_results"],
                ]
        else:
            derived_parameters = {}
            standardization_results = []
            standard_selection = pending_standard_selection()
            llm_standardization = {"standardization_results": [], "diagnostics": []}
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
        if any(item.get("need_human_review") for item in standardization_results):
            human_review_required = True
        if standard_selection.get("need_human_review"):
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
                "material": spring_parameters.get("material", {}).get("value") or "",
                "unit": "mm",
                "overall_status": status,
                "summary": _summary(status, human_review_required, erp_ready),
            },
            "spring_type_detection": classification,
            "spring_template": spring_template,
            "file_info": file_info,
            "spring_parameters": spring_parameters,
            "spring_features": spring_features,
            "standard_selection": standard_selection,
            "derived_parameters": derived_parameters,
            "standardization_results": standardization_results,
            "llm_standardization_diagnostics": llm_standardization["diagnostics"],
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

    def _apply_company_default_accuracy(self, parameters: dict[str, Any], spring_type: str) -> None:
        _apply_company_default_accuracy(parameters, spring_type)

    def _build_spring_features(self, fields: dict[str, dict[str, Any]], spring_type: str) -> dict[str, Any]:
        features = {
            field: self._feature_param(fields, field)
            for field in SPRING_FEATURE_FIELDS
        }
        if spring_type != "compression_spring":
            return features
        return features

    def _feature_param(self, fields: dict[str, dict[str, Any]], field: str) -> dict[str, Any]:
        item = fields.get(field, {})
        return {
            "value": item.get("value") if item else "unknown",
            "source": item.get("source", []) if item else [],
            "evidence": item.get("evidence", "") if item else "",
            "confidence": item.get("confidence", 0) if item else 0,
            "need_human_review": item.get("need_human_review", True) if item else True,
            "page": item.get("page", 1) if item else 1,
            "position": item.get("position") if item else None,
            "suggested_region": item.get("suggested_region", "") if item else "",
        }

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
                    "normalization_source": normalized["normalization_source"],
                    "normalization_confidence": normalized["normalization_confidence"],
                    "normalization_reason": normalized["normalization_reason"],
                    "standard_candidates": normalized["standard_candidates"],
                }
                need_human_review = bool(normalized["need_human_review"])
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
        value = item.get("value")
        extra: dict[str, Any] = {}
        if field == "material" and value not in (None, ""):
            normalized = normalize_material(item.get("raw_value", value))
            value = normalized["value"]
            extra = {
                "raw_value": normalized["raw_value"],
                "standard_value": normalized["standard_value"],
                "normalization_status": normalized["normalization_status"],
                "normalization_source": normalized["normalization_source"],
                "normalization_confidence": normalized["normalization_confidence"],
                "normalization_reason": normalized["normalization_reason"],
            }
        return {
            "value": value,
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
            **extra,
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
            "deflection": value.get("deflection"),
            "deflection_unit": value.get("deflection_unit", "mm"),
            "load_tolerance_upper": value.get("load_tolerance_upper"),
            "load_tolerance_lower": value.get("load_tolerance_lower"),
            "load_tolerance_percent": value.get("load_tolerance_percent"),
            "test_height_type": value.get("test_height_type", ""),
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


def pending_standard_selection() -> dict[str, Any]:
    return {
        "selected_standard": None,
        "standard_label": "",
        "candidate_standards": [],
        "status": "not_started",
        "rules_available": False,
        "confidence": 0,
        "selection_source": "not_started",
        "reason": "等待点击标准化后再进行标准选择和公差计算。",
        "evidence": [],
        "need_human_review": False,
        "references": [],
        "metadata": {},
    }


def apply_standardization_to_review(
    review: dict[str, Any],
    *,
    standard_selection_inference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spring_type = review.get("drawing_summary", {}).get("spring_type")
    spring_type = spring_type or review.get("spring_template", {}).get("spring_type") or "unknown_spring"
    spring_parameters = review.get("spring_parameters") or {}
    _apply_company_default_accuracy(spring_parameters, spring_type)
    apply_company_simple_active_coils(spring_type, spring_parameters)
    standardization = standardize_spring(
        spring_type,
        spring_parameters,
        spring_features=review.get("spring_features") or {},
        standard_selection_inference=standard_selection_inference,
        technical_requirements=review.get("technical_requirements") or [],
    )
    review["standard_selection"] = standardization["standard_selection"]
    review["derived_parameters"] = standardization["derived_parameters"]
    review["standardization_results"] = standardization["standardization_results"]
    review["llm_standardization_diagnostics"] = []
    if review["standardization_results"] or review["standard_selection"].get("selected_standard"):
        review.setdefault("drawing_summary", {})
        review["drawing_summary"]["overall_status"] = "need_review"
    if review["standard_selection"].get("need_human_review") or any(
        item.get("need_human_review") for item in review["standardization_results"]
    ):
        review["human_review_required"] = True
        review["erp_ready"] = False
        review["erp_block_reason"] = review.get("erp_block_reason") or "标准化建议需要人工确认。"
        review.setdefault("drawing_summary", {})
        review["drawing_summary"]["summary"] = "已生成标准化建议，需要人工确认后再导出。"
    return standardization


def _apply_company_default_accuracy(parameters: dict[str, Any], spring_type: str) -> None:
    if spring_type != "compression_spring":
        return
    if any(parameters.get(field, {}).get("value") not in (None, "") for field in ACCURACY_GRADE_FIELDS):
        return
    if "accuracy_grade" not in parameters:
        return
    parameters["accuracy_grade"] = {
        **parameters["accuracy_grade"],
        "value": "2级",
        "source": ["company_default"],
        "evidence": "图纸未标注精度等级，按公司默认二级精度生成标准化建议。",
        "confidence": 0.6,
        "need_human_review": True,
        "default_source": "company_default",
        "default_reason": "图纸未标注精度等级，按公司默认二级精度生成标准化建议。",
    }
