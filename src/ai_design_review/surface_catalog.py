"""Company identity assists editing; confirmed content alone is the drawing text."""
from copy import deepcopy
from functools import lru_cache
import re
from typing import Any

from .io_utils import project_path, read_json
from .technical_requirements import surface_requirement_body

SURFACE_EVIDENCE_VERSION = "surface-evidence/v1"
_NEGATIVE = re.compile(r"(?:不得|禁止|不要|不允许|不准|不需要|无需|未要求|不做|不采用|非|未|无|不)\s*(?:进行|采用|使用|实施|做)?\s*$")
_TERM_ALIASES = {"涂清漆": "油漆-清漆", "清漆": "油漆-清漆", "镀锌五彩": "电镀-镀彩锌"}
_GENERAL_TERMS = ("锌铝片涂层", "锌铝涂层", "ZINCFLAKE", "ZINC FLAKE", "喷丸强化", "喷丸", "SHOT PEENING",
                  "涂漆", "镀锌", "喷塑", "电泳", "表面处理", "表面處理", "FINISH")
_PLATING_CODE = re.compile(r"Fe\s*/\s*Ep\.Zn\d+(?:\.[A-Z0-9]+)+", re.I)
_CLEAR_ZINC_CODE = re.compile(r"Fe\s*/\s*Ep\.Zn(?P<thickness>\d+)\.P\.c2C(?![\w.])", re.I)
_INCOMPLETE_BODY = re.compile(r"待补充|待确认|待核对|未识别|无法辨认|[□�]|[?？]|⟦ENG_|[：:，,；;]$|^[混批]?丸[。.]?$")
_READING_NUMBERS = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
_READING_UNITS = re.compile(r"(?<=\d)\s*(mm|[μµu]m|cm|in|英寸|毫米|微米|小时|分钟|h|min)(?![A-Za-z])", re.I)
_BROAD_TERMS = {"涂漆", "镀锌", "喷塑", "电泳"}


@lru_cache(maxsize=1)
def _catalog_names() -> dict[str, str]:
    return {item["name"]: item["id"] for item in load_surface_catalog()["items"]}


@lru_cache(maxsize=1)
def load_surface_catalog() -> dict[str, Any]:
    catalog = read_json(project_path("config", "company_surface_catalog.json"))
    items = catalog.get("items", [])
    if len(items) != 49 or len({v.get("id") for v in items}) != 49 or len({v.get("name") for v in items}) != 49:
        raise ValueError("公司表面处理目录无效")
    return catalog


def surface_terms(content: Any, *, aliases=False, generic=False, include_negative=False) -> list[tuple[int, int, str, str]]:
    text = str(content or "")
    if not text:
        return []
    names = _catalog_names()
    terms = dict(names)
    if aliases:
        terms.update({alias: names[name] for alias, name in _TERM_ALIASES.items()})
    if generic:
        terms.update({term: "" for term in _GENERAL_TERMS if term not in terms})
    matches, occupied = [], set()
    for term in sorted(terms, key=len, reverse=True):
        pattern = re.escape(term)
        if term.isascii():
            pattern = r"(?<![A-Za-z])" + pattern + r"(?![A-Za-z])"
        for match in re.finditer(pattern, text, re.I):
            if any(i in occupied for i in range(match.start(), match.end())): continue
            prefix = text[max(0, match.start() - 12):match.start()]
            occupied.update(range(match.start(), match.end()))
            if include_negative or not _NEGATIVE.search(prefix):
                matches.append((match.start(), match.end(), match[0], terms[term]))
    return sorted(matches)


def names_in_content(content: Any) -> list[str]:
    return list(dict.fromkeys(item_id for _, _, _, item_id in surface_terms(content)))


def surface_hint(content: Any) -> bool:
    return bool(surface_terms(content, aliases=True, generic=True, include_negative=True) or _PLATING_CODE.search(str(content or "")))


def _review_body_reason(item, *, needs_process=False):
    from .technical_translation import requires_translation
    body = surface_requirement_body(item.get("content"))
    if item.get("unit_pending"):
        return "单位待核对，请对照原图重新填写"
    if not re.search(r"[\u3400-\u9fffA-Za-z]", body) or _INCOMPLETE_BODY.search(body) or (
        needs_process and not _substantive_terms(body)
    ):
        return "表面处理正文残缺，请对照原图补充正文"
    if requires_translation(body) or _PLATING_CODE.search(body):
        return "表面处理转换未完成，请补充中文要求"
    return ""


def _substantive_terms(text):
    return [term for term in surface_terms(text, aliases=True, generic=True, include_negative=True)
            if term[2].upper() not in {"表面处理", "表面處理", "FINISH"}]


def surface_reading_conflict(verification):
    """Compare complete readings of the same note. Partial OCR is only evidence."""
    if not isinstance(verification, dict) or verification.get("status") in {"verified", "reviewed"}:
        return False
    readings = []
    for reading in verification.get("readings") or []:
        if not isinstance(reading, dict) or reading.get("source") == "initial_body":
            continue
        body = surface_requirement_body(reading.get("text"))
        if _INCOMPLETE_BODY.search(body):
            continue
        keys = set()
        for start, _, term, item_id in _substantive_terms(body):
            if term in _BROAD_TERMS:
                continue
            key = item_id or {"SHOTPEENING": "喷丸", "ZINCFLAKE": "锌铝涂层", "锌铝片涂层": "锌铝涂层"}.get(term.upper().replace(" ", ""), term)
            keys.add((key, bool(_NEGATIVE.search(body[max(0, start - 12):start]))))
        numbers = tuple(float(number) for number in _READING_NUMBERS.findall(body.replace("−", "-").replace("–", "-")))
        unit_aliases = {"毫米": "mm", "微米": "μm", "um": "μm", "µm": "μm", "英寸": "in", "小时": "h", "分钟": "min"}
        units = tuple(unit_aliases.get(unit.lower(), unit.lower()) for unit in _READING_UNITS.findall(body))
        if keys or numbers:
            readings.append((keys, numbers, units))
    return any((a and b and not (a <= b or b <= a)) or (av and bv and av != bv) or (au and bu and au != bu)
               for index, (a, av, au) in enumerate(readings) for b, bv, bu in readings[index + 1:])


def _catalog_choice_reason(mapping):
    ids = mapping.get("catalog_ids")
    mode = mapping.get("selection_mode")
    valid = set(_catalog_names().values())
    if mode not in {"auto", "manual", "none"} or not isinstance(ids, list) or (
        any(not isinstance(value, str) or value not in valid for value in ids) or len(set(ids)) != len(ids)
    ) or (mode == "none" and ids):
        return "公司类型无效，请重新选择或置空"
    return ""


def surface_confirmation(item, *, batch=False):
    """Return the normalized decision for a single or bulk confirmation."""
    if item.get("type") != "surface":
        return "", False, None
    mapping = item.get("surface_mapping")
    mapping = mapping if isinstance(mapping, dict) else None
    verification = (mapping or {}).get("verification")
    verification = verification if isinstance(verification, dict) else {}
    needs_review = verification.get("status") == "uncertain" or (mapping or {}).get("conversion_status") == "needs_input"
    conflict = surface_reading_conflict(verification)
    if reason := _review_body_reason(item, needs_process=needs_review):
        return reason, False, None
    if mapping and (reason := _catalog_choice_reason(mapping)):
        return reason, False, None
    if batch and conflict:
        return "表面处理原图读数有冲突，请单项核对", False, None

    body = surface_requirement_body(item.get("content"))
    matches = surface_terms(body, aliases=True)
    mode = (mapping or {}).get("selection_mode", "auto")
    chosen = ((mapping or {}).get("catalog_ids") or [""])[0]
    if chosen and mapping.get("choice_needs_edit"):
        return "已选择公司类型，请核对正文中的工艺名称", False, None
    if chosen and not any(match[3] == chosen for match in matches):
        return "公司类型与正文不一致", False, None
    if not chosen and mode != "none" and not conflict and len(matches) == 1:
        chosen = matches[0][3]
    if not mapping and not chosen and not _substantive_terms(body) and item.get("translation_status") != "translated" and item.get("normalization_status") not in {
        "matched", "alias_matched", "llm_auto_matched", "human_confirmed"
    }:
        return "请先明确表面处理标准术语", False, None
    replacement = [match for match in matches if match[3] == chosen]
    if len(replacement) == 1:
        start, end, _, _ = replacement[0]
        label = next(name for name, item_id in _catalog_names().items() if item_id == chosen)
        body = body[:start] + label + body[end:]
    if chosen and chosen not in names_in_content(body):
        return "公司类型与正文不一致", False, None
    decision = {"content": body, "catalog_ids": [chosen] if chosen else [], "selection_mode": "manual" if chosen else "none",
                "conversion_status": "converted", "verification": {**verification, "status": "reviewed"} if verification else None}
    return "", needs_review or conflict, decision


def verified_surface(item: dict, raw: str, verification: dict) -> dict:
    """Build the Chinese note from the observed line and a verified catalog name."""
    from .technical_translation import requires_translation
    catalog = load_surface_catalog()
    names = {v["id"]: v["name"] for v in catalog["items"]}
    body = surface_requirement_body(raw)
    terms = [term for term in surface_terms(body, aliases=True, generic=True) if term[2].upper() not in {"表面处理", "表面處理", "FINISH"}]
    code = _CLEAR_ZINC_CODE.search(body)
    selected = ""
    matched_term = ""
    status = "unmatched"
    if verification["status"] != "verified":
        status = "needs_input"
    elif code and not terms and not _NEGATIVE.search(body[:code.start()]):
        selected = next(item_id for item_id, name in names.items() if name == "电镀-镀彩锌")
        replacement = f"{names[selected]}，镀层厚度≥{code['thickness']} μm，彩虹铬酸盐处理2级C型"
        body = body[:code.start()] + replacement + body[code.end():]
        matched_term, status = names[selected], "converted"
    elif terms:
        start, end, matched_term, selected = terms[0]
        if selected:
            body = body[:start] + names[selected] + body[end:]
            matched_term, status = names[selected], "converted"
    if verification["status"] == "verified":
        body = re.sub(r"^\s*FINISH\s*[:：]\s*", "表面处理：", body, flags=re.I)
        body = re.sub(r"\bZINC\s*FLAKE\b", "锌铝涂层", body, flags=re.I)
        body = re.sub(r"\bSPECIAL REQUIREMENTS?\s*[:：]\s*", "特殊要求：", body, flags=re.I)
        body = re.sub(r"\bPRESETTING TO SOLID AND SHOT PEENING\b", "立定强压处理至压并，并进行喷丸", body, flags=re.I)
        body = re.sub(r"\bSHOT PEENING\b", "喷丸", body, flags=re.I)
        body = re.sub(r"\bTHICKNESS\s*[:：]?\s*", "厚度", body, flags=re.I)
        body = re.sub(r"(?<=\d)\s*um\b", " μm", body, flags=re.I)
        matched_term = {"ZINCFLAKE": "锌铝涂层", "SHOTPEENING": "喷丸"}.get(matched_term.upper().replace(" ", ""), matched_term)
        if requires_translation(body) or _PLATING_CODE.search(body):
            selected, status = "", "needs_input"
            body, matched_term = surface_requirement_body(raw), ""
    mapping = {"catalog_version": catalog["version"], "catalog_ids": [selected] if selected else [],
               "selection_mode": "auto", "conversion_status": status, "conflict": False,
               "input_snapshot": {"content": raw, "type": "surface"},
               "verification": {**verification, "term": matched_term}}
    result = {**item, "type": "surface", "content": body, "original_content": raw, "raw_content": raw,
              "standard_content": body, "surface_mapping": mapping, "need_human_review": True,
              "normalization_status": "needs_confirmation", "normalization_source": "company_catalog",
              "translation_status": "not_required", "translation_error": "", "translation_error_code": "",
              "translation_error_details": {}, "translation_input_snapshot": None, "translation_output_snapshot": None}
    return result


def mapping_reason(item: dict[str, Any]) -> str:
    mapping = item.get("surface_mapping")
    if not isinstance(mapping, dict): return ""
    ids = mapping.get("catalog_ids")
    if mapping.get("selection_mode") not in {"auto", "manual", "none"}: return "公司类型无效，请重新选择或置空"
    valid = {v["id"] for v in load_surface_catalog()["items"]}
    if not isinstance(ids, list) or any(not isinstance(v, str) or v not in valid for v in ids) or len(set(ids)) != len(ids):
        return "公司类型无效，请重新选择或置空"
    verification = mapping.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    if verification.get("status") == "uncertain":
        return "表面处理原文待核对，请对照原图补充正文"
    if mapping.get("conversion_status") == "needs_input": return "表面处理转换未完成，请补充中文要求"
    if mapping.get("choice_needs_edit") and ids:
        return "已选择公司类型，请核对正文中的工艺名称"
    if mapping.get("selection_mode") == "none": return "" if not ids else "公司类型无效，请重新选择或置空"
    if mapping.get("selection_mode") == "auto" and mapping.get("conversion_status") != "converted" and not (
        verification.get("status") == "verified" and mapping.get("conversion_status") == "unmatched" and not ids
    ):
        return "表面处理转换未完成，请补充中文要求"
    if ids and ids[0] not in names_in_content(item.get("content")):
        return "公司类型与正文不一致"
    return ""


def accept_recognized_surface(item: dict[str, Any]) -> dict[str, Any]:
    """Called on fresh recognition only, never on opening a persisted review."""
    supplied = item.get("surface_mapping")
    verification = supplied.get("verification") if isinstance(supplied, dict) else None
    if isinstance(verification, dict) and verification.get("version") == SURFACE_EVIDENCE_VERSION:
        return deepcopy(item)
    result = deepcopy(item)
    raw = str(item.get("original_content") or item.get("content") or "")
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


def synchronize_surface_review(review: dict[str, Any], previous: dict[str, Any] | None = None, *,
                               confirmed_ids: set[str] | None = None, confirmation_modes: dict[str, str] | None = None) -> None:
    """Validate review decisions and preserve stored recognition evidence."""
    old = {v.get("requirement_id"): v for v in (previous or {}).get("technical_requirements", []) if isinstance(v, dict)}
    for item in review.get("technical_requirements", []):
        if not isinstance(item, dict):
            continue
        mode = (confirmation_modes or {}).get(item.get("requirement_id"))
        before = old.get(item.get("requirement_id"))
        previous_mapping = (before or {}).get("surface_mapping") or {}
        if not isinstance(item.get("surface_mapping"), dict) and not mode and not previous_mapping.get("verification"):
            continue
        if item.get("type") != "surface":
            item.pop("surface_mapping", None)
            continue
        choice = lambda value: {key: (value.get("surface_mapping") or {}).get(key) for key in ("catalog_version", "catalog_ids", "selection_mode", "conversion_status")}
        changed = before and (any(before.get(key) != item.get(key) for key in ("content", "type", "application_scope")) or choice(before) != choice(item))
        stored_evidence = previous_mapping.get("verification")
        mapping = item.get("surface_mapping")
        if isinstance(stored_evidence, dict):
            item["original_content"] = before.get("original_content", "")
            if "raw_content" in before:
                item["raw_content"] = before["raw_content"]
            if not isinstance(mapping, dict):
                mapping = item["surface_mapping"] = deepcopy(previous_mapping)
            submitted = mapping.get("verification") or {}
            submitted = submitted if isinstance(submitted, dict) else {}
            edited_body = surface_requirement_body(item.get("content")) != surface_requirement_body(before.get("content"))
            status = stored_evidence.get("status")
            if edited_body and submitted.get("status") == "manual" and item.get("need_human_review") is not False:
                status = "manual"
            mapping["verification"] = {**stored_evidence, "term": submitted.get("term", stored_evidence.get("term", "")), "status": status}
        legacy_invalid = False
        if mode and item.get("need_human_review") is False:
            reason, _, decision = surface_confirmation(item, batch=mode == "batch")
            if reason:
                if isinstance(stored_evidence, dict) or (mapping or {}).get("verification"):
                    raise ValueError(reason)
                legacy_invalid = True
            else:
                mapping = item.setdefault("surface_mapping", {})
                item["content"] = decision["content"]
                mapping.update(catalog_version=load_surface_catalog()["version"], catalog_ids=decision["catalog_ids"],
                               selection_mode=decision["selection_mode"], conversion_status=decision["conversion_status"])
                mapping.pop("choice_needs_edit", None)
                if decision["verification"] is not None:
                    mapping["verification"] = decision["verification"]
                mapping["input_snapshot"] = {"content": item["content"], "type": "surface"}
                item.update(translation_status="not_required", translation_error="", translation_error_code="",
                            translation_error_details={}, translation_input_snapshot=None, translation_output_snapshot=None)
                for confirmation in (review.get("manual_confirmations") or {}).values():
                    if isinstance(confirmation, dict) and confirmation.get("requirement_id") == item.get("requirement_id"):
                        confirmation.update(value=item["content"], surface_review={"mode": mode, "catalog_ids": mapping["catalog_ids"]})
                snapshot = item.get("confirmation_snapshot")
                if isinstance(snapshot, dict):
                    snapshot.update(content=item["content"], surface_mapping=choice(item))
        if not isinstance(item.get("surface_mapping"), dict):
            if legacy_invalid:
                item["need_human_review"] = True
            continue
        if (changed or item.get("requirement_id") in (confirmed_ids or set())) and isinstance(item["surface_mapping"].get("catalog_ids"), list):
            item["surface_mapping"]["catalog_ids"] = item["surface_mapping"]["catalog_ids"][:1]
        reason = mapping_reason(item)
        item["surface_mapping"]["conflict"] = bool(item["surface_mapping"].get("choice_needs_edit")) or reason == "公司类型与正文不一致"
        item["standard_content"] = str(item.get("content") or "").strip()
        unrecorded_confirmation = (isinstance(stored_evidence, dict) and before.get("need_human_review") is not False
                                   and item.get("requirement_id") not in (confirmed_ids or set()))
        if reason or legacy_invalid or unrecorded_confirmation or changed and item.get("requirement_id") not in (confirmed_ids or set()):
            item["need_human_review"] = True
            for key, value in (review.get("manual_confirmations") or {}).items():
                if isinstance(value, dict) and (value.get("requirement_id") == item.get("requirement_id") or value.get("target_field") == f"technical_requirements.{item.get('requirement_id')}"):
                    value["confirmed"] = False


def surface_catalog_prompt() -> str:
    import json
    return """
公司表面处理转换（仅作用于实际表面处理，其他参数和要求正常识别）：
按正文和上下文判断，不能因旧分类是process/other漏掉表面处理。每条表面处理返回type=surface，original_content保留原图完整文字，content和surface_mapping.converted_content均为公司名称加完整中文工艺条件。
技术要求逐条返回original_number、page、position（原页左上角0到1归一化的完整原文文字框；无法定位时为null）。遇到表格“表面处理”栏时，正文只抄工艺单元格，original_content可保留栏名。看清原文再抄写，保留抛丸与喷丸的区别，涂清漆必须保留“清”字；只写锌铝涂层或ZINCFLAKE时不指定具体产品。
在原条目内附加surface_mapping={"catalog_ids":[公司ID],"conversion_status":"converted|unmatched|needs_input","converted_content":"完整中文要求"}。只允许选目录ID，每条只关联一个公司类型；复合工艺采用原工艺顺序中的第一项，其余工艺及条件完整保留正文。同名多次工序在正文保留顺序。
厚度、单位、标准、等级、部位、工序顺序、除氢和否定条件不得删除或补造。代号要解释成中文，不能把Fe/Ep.Zn15.P.c2C（除氢）原样放在成图正文；其中文为电镀-镀彩锌，镀层厚度≥15 μm，彩虹铬酸盐处理2级C型，并进行除氢处理。仅写镀锌、喷塑、电泳且缺细分信息时不猜白锌、颜色或其他默认值。无法明确映射或完整解释时catalog_ids=[]并返回unmatched或needs_input，保留原文供人工补充。复合要求的其余内容完整保留，不拆删、不重排。表面粗糙度不是本目录的表面处理。
公司目录（只包含ID和名称，无旧备注或默认规则）：
""" + json.dumps(load_surface_catalog()["items"], ensure_ascii=False, separators=(",", ":"))
