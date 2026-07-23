from __future__ import annotations

from typing import Any

from ..standard_selector import COLD_COILED_STANDARD, select_standard
from .coil_counts import derive_active_coils
from .compression import (
    apply_formula_compression_solid_height,
    derive_compression_parameters,
    standardize_compression_spring,
)
from .stiffness import apply_formula_compression_spring_rate


def standardize_spring(
    spring_type: str,
    spring_parameters: dict[str, Any],
    spring_features: dict[str, Any] | None = None,
    standard_selection_inference: dict[str, Any] | None = None,
    technical_requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if spring_type == "compression_spring":
        apply_formula_compression_solid_height(spring_parameters)
        apply_formula_compression_spring_rate(spring_parameters, spring_features)
    standard_selection = select_standard(
        spring_type,
        spring_parameters,
        spring_features=spring_features,
        llm_inference=standard_selection_inference,
        technical_requirements=technical_requirements,
    )
    if spring_type == "compression_spring":
        if standard_selection.get("selected_standard") == COLD_COILED_STANDARD:
            payload = standardize_compression_spring(spring_parameters, spring_features)
            _attach_standard_references(payload["standardization_results"], standard_selection)
            if _uses_company_default_accuracy(spring_parameters):
                _mark_results_using_default_accuracy(payload["standardization_results"], spring_parameters)
            if standard_selection.get("need_human_review"):
                _mark_results_need_standard_review(payload["standardization_results"], standard_selection)
            payload["standard_selection"] = standard_selection
            return payload
        return {
            "derived_parameters": derive_compression_parameters(spring_parameters),
            "standardization_results": [],
            "standard_selection": standard_selection,
        }
    return {
        "derived_parameters": derive_active_coils(spring_type, spring_parameters),
        "standardization_results": [],
        "standard_selection": standard_selection,
    }


DEFAULT_ACCURACY_RULE_IDS = {
    "GBT1239.2-DIA",
    "GBT1239.2-FREE",
    "GBT1239.2-PERP",
    "GBT1239.2-STRAIGHT",
    "GBT1239.2-LOAD",
    "GBT1239.2-STIFF",
}


def _uses_company_default_accuracy(spring_parameters: dict[str, Any]) -> bool:
    item = spring_parameters.get("accuracy_grade")
    return bool(isinstance(item, dict) and item.get("default_source") == "company_default")


def _mark_results_using_default_accuracy(results: list[dict[str, Any]], spring_parameters: dict[str, Any]) -> None:
    grade = (spring_parameters.get("accuracy_grade") or {}).get("value") or "2级"
    note = f"精度等级采用公司默认{grade}，需人工确认。"
    for item in results:
        if item.get("rule_id") not in DEFAULT_ACCURACY_RULE_IDS:
            continue
        item["need_human_review"] = True
        basis = str(item.get("basis") or "")
        if note not in basis:
            item["basis"] = f"{basis} {note}".strip()
        item.setdefault("metadata", {})
        item["metadata"]["accuracy_grade_source"] = "company_default"
        item["metadata"]["accuracy_grade_value"] = grade
        item["metadata"]["accuracy_grade_need_human_review"] = True
        item["metadata"]["accuracy_grade_reason"] = (spring_parameters.get("accuracy_grade") or {}).get("default_reason") or note


def _mark_results_need_standard_review(results: list[dict[str, Any]], standard_selection: dict[str, Any]) -> None:
    reason = standard_selection.get("reason") or "标准选择需要人工确认。"
    for item in results:
        item["need_human_review"] = True
        item.setdefault("metadata", {})
        item["metadata"]["standard_selection_status"] = standard_selection.get("status")
        item["metadata"]["standard_selection_reason"] = reason


def _attach_standard_references(results: list[dict[str, Any]], standard_selection: dict[str, Any]) -> None:
    references = standard_selection.get("references") or []
    if not references:
        return
    for item in results:
        item.setdefault("metadata", {})
        item["metadata"]["standard_references"] = references
