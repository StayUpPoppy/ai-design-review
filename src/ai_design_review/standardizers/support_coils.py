"""Support-coil provenance and reconciliation. Mirrored by the browser calculator."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .calculation_state import human_override, number, same_inputs, sources

SNAPSHOT_KEYS = ("value", "unit", "need_human_review", "source", "evidence", "page", "position", "tolerance_upper", "tolerance_lower", "confirmation_snapshot")


def support_origin(item: dict[str, Any]) -> str:
    text = str(item.get("evidence") or "")
    if re.search(r"计算|推算|推导|相减|差值|默认|假设|derived|calculated|(?:总圈|total).*(?:有效|active).*[=＝]", text, re.I):
        return "inferred"
    if re.search(r"(?:两端|双端|左右两端).{0,8}(?:合计|共|总)|总支承圈数|支承圈数合计|total\s+support", text, re.I):
        return "drawing_total"
    if re.search(r"单端|每端|各端|两端各|每一端|per\s*end|each\s*end", text, re.I) and (
        re.search(r"支承|支撑|support", text, re.I) or re.search(r"(?:单端|每端|各端|两端各|每一端)\s*[:：]?\s*\d+(?:\.\d+)?\s*圈", text)
    ):
        return "drawing_single_end"
    return "unknown"


def recognized(item: dict[str, Any]) -> bool:
    return any(re.search(r"qwen|ocr|vision|drawing|werk24|pdf_text|cad|dxf|dwg|paddle|azure", s) for s in sources(item))


def classify_support_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("field") != "support_coils":
        return candidate
    result = deepcopy(candidate)
    result["support_coils_origin"] = support_origin(candidate)
    result["support_coils_original"] = {k: deepcopy(candidate[k]) for k in SNAPSHOT_KEYS if k in candidate}
    return result


def asymmetric_support(review: dict[str, Any]) -> bool:
    params = review.get("spring_parameters") or {}
    item = params.get("support_coils") or {}
    if isinstance(item, dict) and item.get("support_coils_symmetry") == "asymmetric":
        return True
    texts = [str((params.get(f) or {}).get("evidence") or "") for f in ("support_coils", "end_type") if isinstance(params.get(f), dict)]
    texts += [str(t.get("content") or "") for t in review.get("technical_requirements") or [] if isinstance(t, dict)]
    for text in texts:
        if re.search(r"两端.{0,12}(?:不对称|非对称|支承圈数不同)|左右端.{0,8}(?:不同|不等)|asymmetric\s+(?:end|support)", text, re.I):
            return True
        match = re.search(r"左端(?:支承)?(?:圈数)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*圈.{0,12}右端(?:支承)?(?:圈数)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*圈", text)
        if match and float(match[1]) != float(match[2]):
            return True
    return False


def prepare_support(review: dict[str, Any]) -> None:
    item = (review.get("spring_parameters") or {}).get("support_coils")
    if not isinstance(item, dict):
        return
    if recognized(item) and not human_override(item) and not item.get("formula_calculation_kind"):
        item["support_coils_origin"] = support_origin(item)
        if "support_coils_original" not in item and item.get("value") not in (None, ""):
            item["support_coils_original"] = {k: deepcopy(item[k]) for k in SNAPSHOT_KEYS if k in item}
        # Unverified model arithmetic must not become an input to other formulas.
        if item["support_coils_origin"] != "drawing_single_end" and item.get("need_human_review") is not False:
            item["derived_value_stale"] = True


def reconcile_support(review: dict[str, Any], calculated: dict[str, Any]) -> None:
    params = review.get("spring_parameters") or {}
    old = params.get("support_coils")
    item = old if isinstance(old, dict) else {"value": old}
    formula = item.get("formula_calculation_kind") == "support_coils"
    origin = item.get("support_coils_origin") or support_origin(item)
    automatic = formula or recognized(item) and origin != "drawing_single_end"
    protected = human_override(item) or origin == "drawing_single_end" or not automatic and item.get("value") not in (None, "")
    value = number(calculated.get("value"))
    input_changed = not same_inputs(item.get("formula_calculation_inputs") or item.get("support_coils_input_baseline"), calculated["inputs"])
    roots = [params.get(f) or {} for f in ("total_coils", "active_coils")]
    waiting = any(human_override(p) and p.get("need_human_review") is not False for p in roots)
    both_confirmed = all(p.get("need_human_review") is False for p in roots)
    edited = any(human_override(p) for p in roots) or item.get("support_coils_recompute_pending") is True
    item.setdefault("support_coils_input_baseline", deepcopy(calculated["inputs"]))
    item.pop("support_coils_conflict", None)
    item.pop("support_coils_notice", None)
    item.pop("support_coils_waiting_confirmation", None)
    if protected:
        if formula:
            item.pop("derived_value_stale", None)
            item.pop("formula_recommendation_stale", None)
        if value is not None and number(item.get("value")) is not None and abs(float(item["value"]) - value) > 1e-9:
            item["support_coils_conflict"] = "当前单端支承圈数与 (总圈数－有效圈数)/2 不一致，请核对原图或人工值"
            item["formula_recalculation_candidate"] = deepcopy(calculated)
            item["support_coils_waiting_confirmation"] = waiting
        else:
            item.pop("formula_recalculation_candidate", None)
            if value is None:
                item["support_coils_notice"] = calculated.get("reason") or "缺少有效计算依据"
        return
    if waiting:
        item.update(derived_value_stale=True, formula_recommendation_stale=True,
                    formula_recalculation_candidate=deepcopy(calculated), support_coils_recompute_pending=True,
                    support_coils_waiting_confirmation=True, formula_calculation_reason="总圈数和有效圈数当前值均确认后，将自动重算单端支承圈数")
        return
    if item.get("need_human_review") is False and (value is None or not input_changed or not (both_confirmed and edited)):
        from .calculation_state import preserve_candidate
        preserve_candidate(item, calculated)
        return
    if value is None:
        if automatic:
            item.update(derived_value_stale=True, formula_recommendation_stale=True,
                        formula_recalculation_candidate=deepcopy(calculated), formula_calculation_reason=calculated.get("reason") or "缺少有效计算依据")
        else:
            item["support_coils_notice"] = calculated.get("reason") or "缺少有效计算依据"
        return
    target = old if isinstance(old, dict) else params.setdefault("support_coils", {})
    before = {k: deepcopy(target[k]) for k in (*SNAPSHOT_KEYS, "formula_calculation_inputs") if k in target}
    changed = number(target.get("value")) != round(value, 4) or input_changed or not formula
    target.update(field="support_coils", value=round(value, 4), unit="turns", source=["formula_calculation"], need_human_review=True,
                  confidence=0.88, formula=calculated["formula"], evidence=calculated["basis"], source_fields=calculated["source_fields"],
                  formula_calculation_kind="support_coils", formula_calculation_status=calculated["status"],
                  formula_calculation_inputs=deepcopy(calculated["inputs"]), support_coils_input_baseline=deepcopy(calculated["inputs"]),
                  derived_value_stale=False, formula_recommendation_stale=False)
    if changed:
        previous_confirmation = (review.get("manual_confirmations") or {}).pop("support_coils", None)
        target.pop("confirmation_snapshot", None)
        target["support_coils_adjustment"] = {"before": before, "after": {"value": target["value"], "unit": "turns", "inputs": deepcopy(calculated["inputs"])},
                                                "previous_confirmation": deepcopy(previous_confirmation), "reason": "confirmed_coil_inputs_changed" if both_confirmed and edited else "support_coils_formula_reconciliation", "audit_recorded": False}
    for key in ("formula_recalculation_candidate", "formula_calculation_reason", "support_coils_recompute_pending", "support_coils_waiting_confirmation"):
        target.pop(key, None)
