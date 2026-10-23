"""Company identity assists editing; confirmed content alone is the drawing text."""
from copy import deepcopy
from functools import lru_cache
import re
from typing import Any

from .io_utils import project_path, read_json


@lru_cache(maxsize=1)
def load_surface_catalog() -> dict[str, Any]:
    catalog = read_json(project_path("config", "company_surface_catalog.json"))
    items = catalog.get("items", [])
    if len(items) != 49 or len({v.get("id") for v in items}) != 49 or len({v.get("name") for v in items}) != 49:
        raise ValueError("公司表面处理目录无效")
    return catalog


def names_in_content(content: Any) -> list[str]:
    """Only exact positive names, longest-first; no colour/default inference."""
    text = str(content or "")
    matches, occupied = [], set()
    for item in sorted(load_surface_catalog()["items"], key=lambda v: -len(v["name"])):
        for match in re.finditer(re.escape(item["name"]), text):
            if any(i in occupied for i in range(match.start(), match.end())): continue
            prefix = text[max(0, match.start() - 12):match.start()]
            if re.search(r"(?:不得|禁止|不要|不允许|不准|不需要|无需|未要求|不做|不采用|非|未|无|不)\s*(?:进行|采用|使用|实施|做)?\s*$", prefix): continue
            occupied.update(range(match.start(), match.end()))
            matches.append((match.start(), item["id"]))
    return list(dict.fromkeys(v for _, v in sorted(matches)))


def mapping_reason(item: dict[str, Any]) -> str:
    mapping = item.get("surface_mapping")
    if not isinstance(mapping, dict): return ""
    ids = mapping.get("catalog_ids")
    if mapping.get("selection_mode") not in {"auto", "manual", "none"}: return "公司类型无效，请重新选择或置空"
    valid = {v["id"] for v in load_surface_catalog()["items"]}
    if not isinstance(ids, list) or any(not isinstance(v, str) or v not in valid for v in ids) or len(set(ids)) != len(ids):
        return "公司类型无效，请重新选择或置空"
    if mapping.get("conversion_status") == "needs_input": return "表面处理转换未完成，请补充中文要求"
    if mapping.get("selection_mode") == "none": return "" if not ids else "公司类型无效，请重新选择或置空"
    if mapping.get("selection_mode") == "auto" and mapping.get("conversion_status") != "converted":
        return "表面处理转换未完成，请补充中文要求"
    if ids and ids[0] not in names_in_content(item.get("content")):
        return "公司类型与正文不一致"
    return ""


def accept_recognized_surface(item: dict[str, Any]) -> dict[str, Any]:
    """Called on fresh recognition only, never on opening a persisted review."""
    result = deepcopy(item)
    raw = str(item.get("original_content") or item.get("content") or "")
    supplied = item.get("surface_mapping")
    if not isinstance(supplied, dict): supplied = {}
    ids = supplied.get("catalog_ids", [])
    valid = {v["id"] for v in load_surface_catalog()["items"]}
    invalid = not isinstance(ids, list) or any(not isinstance(v, str) or v not in valid for v in ids) or len(set(ids)) != len(ids)
    converted = supplied.get("converted_content")
    status = supplied.get("conversion_status")
    if invalid or status not in {"converted", "unmatched", "needs_input"}:
        status = "needs_input"
    if status == "converted" and (not isinstance(converted, str) or not converted.strip()): status = "needs_input"
    if status == "converted" and not ids: status = "needs_input"
    mapping = {"catalog_version": load_surface_catalog()["version"], "catalog_ids": [] if invalid else ids[:1],
               "selection_mode": "auto", "conversion_status": status, "conflict": False,
               "input_snapshot": {"content": raw, "type": item.get("type", "surface")}}
    result.update(type="surface", raw_content=raw, original_content=raw, surface_mapping=mapping, need_human_review=True)
    if status == "converted":
        result["content"] = converted.strip()
        result.update(translation_status="translated", translation_error="", translation_error_code="", translation_error_details={},
                      translation_output_snapshot={"content": result["content"], "type": "surface"})
    else:
        result["content"] = raw
    result["standard_content"] = result["content"]
    result.update(normalization_status="needs_confirmation", normalization_source="company_catalog")
    mapping["conflict"] = bool(mapping_reason(result)) and status == "converted"
    return result


def synchronize_surface_review(review: dict[str, Any], previous: dict[str, Any] | None = None, *, confirmed_ids: set[str] | None = None) -> None:
    """Enforce metadata consistency at saves without rewriting human text."""
    old = {v.get("requirement_id"): v for v in (previous or {}).get("technical_requirements", []) if isinstance(v, dict)}
    for item in review.get("technical_requirements", []):
        if not isinstance(item, dict) or not isinstance(item.get("surface_mapping"), dict): continue
        if item.get("type") != "surface":
            item.pop("surface_mapping", None)
            continue
        before = old.get(item.get("requirement_id"))
        choice = lambda value: {key: (value.get("surface_mapping") or {}).get(key) for key in ("catalog_version", "catalog_ids", "selection_mode", "conversion_status")}
        changed = before and (any(before.get(key) != item.get(key) for key in ("content", "type", "application_scope")) or choice(before) != choice(item))
        if (changed or item.get("requirement_id") in (confirmed_ids or set())) and isinstance(item["surface_mapping"].get("catalog_ids"), list):
            item["surface_mapping"]["catalog_ids"] = item["surface_mapping"]["catalog_ids"][:1]
        reason = mapping_reason(item)
        item["surface_mapping"]["conflict"] = reason == "公司类型与正文不一致"
        item["standard_content"] = str(item.get("content") or "").strip()
        if reason or changed and item.get("requirement_id") not in (confirmed_ids or set()):
            item["need_human_review"] = True
            for key, value in (review.get("manual_confirmations") or {}).items():
                if isinstance(value, dict) and (value.get("requirement_id") == item.get("requirement_id") or value.get("target_field") == f"technical_requirements.{item.get('requirement_id')}"):
                    value["confirmed"] = False


def surface_catalog_prompt() -> str:
    import json
    return """
公司表面处理转换（仅作用于实际表面处理，其他参数和要求正常识别）：
按正文和上下文判断，不能因旧分类是process/other漏掉表面处理。每条表面处理返回type=surface，original_content保留原图完整文字，content和surface_mapping.converted_content均为公司名称加完整中文工艺条件。
在原条目内附加surface_mapping={"catalog_ids":[公司ID],"conversion_status":"converted|unmatched|needs_input","converted_content":"完整中文要求"}。只允许选目录ID，每条只关联一个公司类型；复合工艺采用原工艺顺序中的第一项，其余工艺及条件完整保留正文。同名多次工序在正文保留顺序。
厚度、单位、标准、等级、部位、工序顺序、除氢和否定条件不得删除或补造。代号要解释成中文，不能把Fe/Ep.Zn15.P.c2C（除氢）原样放在成图正文；其中文为电镀-镀彩锌，镀层厚度≥15 μm，彩虹铬酸盐处理2级C型，并进行除氢处理。仅写镀锌、喷塑、电泳且缺细分信息时不猜白锌、颜色或其他默认值。无法明确映射或完整解释时catalog_ids=[]并返回unmatched或needs_input，保留原文供人工补充。复合要求的其余内容完整保留，不拆删、不重排。表面粗糙度不是本目录的表面处理。
公司目录（只包含ID和名称，无旧备注或默认规则）：
""" + json.dumps(load_surface_catalog()["items"], ensure_ascii=False, separators=(",", ":"))
