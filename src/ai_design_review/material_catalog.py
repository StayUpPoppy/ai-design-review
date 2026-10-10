"""Company compression-material selection; never infer alloy equivalence."""
from __future__ import annotations

import math
import re
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from .io_utils import project_path, read_json
from .material_terms import normalize_material_key


MATERIAL_CATALOG_PATH = project_path("config", "compression_material_catalog.json")
MATERIAL_CATALOG_KEYS = (
    "material_id", "material_catalog_version", "material_selection_source",
    "material_selection_reason", "material_substitution_evidence", "material_match_status",
    "primary_materials", "alternative_materials", "material_alternatives",
)
_CURRENT_SELECTION_FIELDS = ("standard_value", "material_id", "material_catalog_version")
_ALLOWANCE = re.compile(
    r"允许.{0,12}(?:换用|替代|代用|更换|选用|使用)|(?:可|可以)(?:换用|改用|替换为)|"
    r"допускается.{0,50}(?:замена|заменить)|(?:may|can)\s+be\s+(?:replaced|substituted)|"
    r"(?:permitted|allowed)\s+(?:replacement|substitut)|(?:alternative|substitute)\s+material",
    re.IGNORECASE,
)
_NEGATED_ALLOWANCE = re.compile(
    r"不允许|未允许|未经允许|禁止|不得|不准|不能|不可|"
    r"\b(?:not|never|no)\b|\b(?:не|нельзя|запрещено|запрещается)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def load_material_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalog = read_json(Path(path) if path else MATERIAL_CATALOG_PATH)
    ids: set[str] = set()
    for item in catalog.get("items", []):
        material_id = str(item.get("id") or "")
        modulus = item.get("shear_modulus_mpa")
        if (not material_id or material_id in ids or not item.get("display_name")
                or not item.get("standard_value") or isinstance(modulus, bool)
                or not isinstance(modulus, (int, float)) or not math.isfinite(modulus) or modulus <= 0):
            raise ValueError("公司材料目录包含无效或重复条目。")
        ids.add(material_id)
    if len(ids) != 15 or not catalog.get("version"):
        raise ValueError("公司压缩弹簧材料目录必须包含 15 种材料及版本。")
    return catalog


def material_catalog_matches(value: Any) -> list[dict[str, Any]]:
    """Match explicit complete grades within material text, not grade prefixes."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return []
    key = normalize_material_key(text)
    # A standalone size "70" is not a carbon-steel designation. Only the
    # explicitly configured grade "70#" or named material is accepted.
    if key.isdigit() and "#" not in text:
        return []
    matches = []
    for item in load_material_catalog()["items"]:
        aliases = [item["display_name"], item["standard_value"], *item.get("aliases", [])]
        if key in {normalize_material_key(alias) for alias in aliases} or any(
            _contains_grade(text, str(alias)) for alias in aliases
        ):
            matches.append(deepcopy(item))
    return matches


def match_material_catalog(value: Any) -> dict[str, Any] | None:
    matches = material_catalog_matches(value)
    return matches[0] if len(matches) == 1 else None


def _engineering_character(character: str) -> bool:
    # Chinese labels may directly adjoin a grade. Other alphabetic suffixes
    # remain part of that grade, including Cyrillic characters.
    return character.isalnum() and not ("\u3400" <= character <= "\u9fff") or character == "_"


def _contains_grade(text: str, alias: str) -> bool:
    pattern = re.escape(unicodedata.normalize("NFKC", alias))
    pattern = pattern.replace(r"\ ", r"\s*")
    pattern = pattern.replace(r"\-", r"[\s-]*")
    for found in re.finditer(pattern, text, flags=re.IGNORECASE):
        before = text[found.start() - 1] if found.start() else ""
        after = text[found.end()] if found.end() < len(text) else ""
        if not _engineering_character(before) and not _engineering_character(after):
            return True
    return False


def _sources(parameter: dict[str, Any]) -> list[str]:
    sources = parameter.get("source") or []
    return [str(value).lower() for value in (sources if isinstance(sources, list) else [sources])]


def _protected(parameter: dict[str, Any]) -> bool:
    return (parameter.get("need_human_review") is False or parameter.get("human_modified") is True
            or parameter.get("human_confirmed") is True or any(
                source.startswith("human") or source in {"manual", "manual_input", "standardization_chat", "ai_chat"}
                for source in _sources(parameter)
            ) or parameter.get("material_selection_source") in {"manual", "ai"})


def _has_user_edits(item: dict[str, Any]) -> bool:
    return item.get("human_modified") is True or any(
        source in {"human_edited", "human_modified", "human_added", "manual", "manual_input", "ai_chat", "standardization_chat"}
        for source in _sources(item)
    )


def _apply_entry(parameter: dict[str, Any], entry: dict[str, Any], source: str) -> dict[str, Any]:
    result = deepcopy(parameter)
    result.update({
        "value": entry["display_name"], "standard_value": entry["standard_value"],
        "material_id": entry["id"], "material_catalog_version": load_material_catalog()["version"],
        "material_selection_source": source, "normalization_status": "matched",
        "normalization_source": "compression_material_catalog",
        "material_match_status": "matched",
    })
    return result


def select_compression_material(parameter: dict[str, Any], value: Any, *, selection_source: str = "manual") -> dict[str, Any]:
    """Select only a whole catalog grade/name; preserve drawing evidence."""
    result = deepcopy(parameter)
    text = str(value or "").strip()
    if text:
        entry = match_material_catalog(text)
        if not entry or normalize_material_key(text) not in {
            normalize_material_key(alias) for alias in [entry["display_name"], entry["standard_value"], *entry["aliases"]]
        }:
            raise ValueError("材料必须从公司材料目录的 15 种材料中选择。")
        result = _apply_entry(result, entry, selection_source)
    else:
        result["value"] = ""
        for key in _CURRENT_SELECTION_FIELDS:
            result.pop(key, None)
        result["material_catalog_version"] = load_material_catalog()["version"]
        result["material_selection_source"] = selection_source
        result["normalization_status"] = "unmatched"
        result["material_match_status"] = "empty"
    result.pop("material_substitution_evidence", None)
    result.pop("material_selection_reason", None)
    result["material_selection_reason"] = (
        "用户手动选择公司材料目录。" if text and selection_source == "manual" else
        "用户采纳 AI 材料选择方案。" if text and selection_source == "ai" else
        "材料已清空，请选择。" if not text else "材料已匹配公司材料目录。"
    )
    result["need_human_review"] = True
    return result


def normalize_compression_material_parameter(
    parameter: dict[str, Any], *, alternatives: Any = None, preserve_existing: bool = True,
) -> dict[str, Any]:
    result = deepcopy(parameter)
    if preserve_existing and _protected(result):
        return result
    if result.get("material_catalog_version") and result.get("material_selection_source"):
        # Already selected (including a deliberate blank) is the current source.
        current = result.get("value")
        entry = match_material_catalog(current)
        if entry:
            return _apply_entry(result, entry, result["material_selection_source"])
        if current in (None, "") and result.get("material_selection_source") != "drawing":
            for key in ("standard_value", "material_id"):
                result.pop(key, None)
            return result
    raw = str(result.get("raw_value") or result.get("value") or "").strip()
    result["raw_value"] = raw
    primary_candidates = result.get("primary_materials") or []
    primary_keys = set()
    for candidate in primary_candidates:
        candidate_value = str(candidate.get("raw_value") or candidate.get("value") or "") if isinstance(candidate, dict) else str(candidate)
        primary_text = _primary_text(candidate_value)
        if primary_text:
            matched = match_material_catalog(primary_text)
            primary_keys.add("catalog:" + matched["id"] if matched else "raw:" + normalize_material_key(primary_text))
    if len(primary_keys) > 1:
        result = _empty_recognition(result, "识别到多个主要材料候选，请选择。")
        result["material_match_status"] = "conflict"
        result["need_human_review"] = True
        return result
    primary = material_catalog_matches(_primary_text(raw))
    if len(primary) == 1:
        result = _apply_entry(result, primary[0], "drawing")
        result["material_selection_reason"] = "图纸材料唯一匹配公司材料目录。"
        result.pop("material_substitution_evidence", None)
    elif len(primary) > 1:
        result = _empty_recognition(result, "识别到多个材料候选，请选择。")
        result["material_match_status"] = "conflict"
    else:
        available = alternatives or result.get("alternative_materials") or result.get("material_alternatives") or []
        available = list(available) if isinstance(available, list) else [available]
        if _ALLOWANCE.search(raw):
            available.append({"value": raw, "evidence": raw})
        permitted = _permitted_alternatives(available)
        by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for candidate in permitted:
            for entry in material_catalog_matches(candidate.get("value") or candidate.get("evidence")):
                by_id[entry["id"]] = entry, candidate
        if len(by_id) == 1:
            entry, evidence = next(iter(by_id.values()))
            result = _apply_entry(result, entry, "drawing_substitute")
            result["material_substitution_evidence"] = deepcopy(evidence)
            result["material_selection_reason"] = "原图材料未匹配，采用图纸明确允许的唯一目录替代材料。"
        else:
            reason = ("图纸允许多个替代材料，请选择。" if len(by_id) > 1 else
                      "原图材料未匹配公司材料目录，请选择。" if raw else "未识别到材料，请选择。")
            result = _empty_recognition(result, reason)
            if len(by_id) > 1:
                result["material_match_status"] = "conflict"
    result["need_human_review"] = True
    return result


def _empty_recognition(parameter: dict[str, Any], reason: str) -> dict[str, Any]:
    result = deepcopy(parameter)
    result.update({"value": "", "standard_value": "", "material_selection_source": "drawing",
                   "material_catalog_version": load_material_catalog()["version"],
                   "material_selection_reason": reason, "normalization_status": "unmatched",
                   "material_match_status": "unmatched" if parameter.get("raw_value") else "empty"})
    result.pop("material_id", None)
    result.pop("material_substitution_evidence", None)
    return result


def _primary_text(text: str) -> str:
    allowance = _ALLOWANCE.search(text)
    prefix = text[:allowance.start()].strip() if allowance else text
    return " ".join(piece.strip() for piece in re.split(r"[;；。,，\n]", prefix)
                    if piece.strip() and not _NEGATED_ALLOWANCE.search(piece))


def _permitted_alternatives(alternatives: Any) -> list[dict[str, Any]]:
    candidates = alternatives if isinstance(alternatives, list) else [alternatives]
    result = []
    for candidate in candidates:
        if isinstance(candidate, str):
            candidate = {"value": candidate, "evidence": candidate}
        if not isinstance(candidate, dict):
            continue
        evidence = str(candidate.get("evidence") or candidate.get("original_content") or "")
        scopes = _allowance_scopes(evidence)
        if scopes:
            for scope in scopes:
                result.append({**candidate, "value": scope, "evidence": evidence, "explicitly_allowed": True})
        elif (candidate.get("explicitly_allowed") is True and not _ALLOWANCE.search(evidence)
              and not _NEGATED_ALLOWANCE.search(evidence)):
            result.append({**candidate, "evidence": evidence, "explicitly_allowed": True})
    return result


def _allowance_scopes(text: str) -> list[str]:
    """Only grades in an affirmative replacement clause are alternatives.

    Neighboring dimensions, fixture materials and negated instructions are
    not substitution evidence. Ambiguous prose is left for manual selection.
    """
    scopes = []
    clauses = re.split(r"[;；。\n]+|(?<!\d)[.!?]|[.!?](?!\d)", text)
    for clause in clauses:
        pieces = re.split(r"(?<!\d)[,，]|[,，](?!\d)", clause)
        permit_continuation = False
        for piece in pieces:
            found = _ALLOWANCE.search(piece)
            if found:
                if _NEGATED_ALLOWANCE.search(piece):
                    permit_continuation = False
                    continue
                scopes.append(piece[found.end():].strip())
                permit_continuation = True
            elif permit_continuation:
                # An explicit comma-separated list may continue with another
                # complete grade, but not an unrelated explanatory sentence.
                grade = re.sub(r"^(?:或|和|及|或者|or\b|and\b)\s*", "", piece.strip(), flags=re.IGNORECASE)
                entry = match_material_catalog(grade)
                if entry and normalize_material_key(grade) in {
                    normalize_material_key(alias) for alias in [entry["display_name"], entry["standard_value"], *entry["aliases"]]
                }:
                    scopes.append(grade)
                else:
                    permit_continuation = False
    return scopes


def ensure_compression_material(review: dict[str, Any]) -> None:
    spring_type = ((review.get("drawing_summary") or {}).get("spring_type")
                   or (review.get("spring_template") or {}).get("spring_type"))
    if spring_type != "compression_spring":
        return
    parameters = review.setdefault("spring_parameters", {})
    original = parameters.get("material") or {}
    if not isinstance(original, dict):
        original = {"value": original, "need_human_review": True}
    alternatives = list(review.get("material_alternatives") or [])
    alternatives.extend(original.get("alternative_materials") or original.get("material_alternatives") or [])
    for requirement in review.get("technical_requirements") or []:
        if not isinstance(requirement, dict):
            continue
        keys = ("original_content",) if _has_user_edits(requirement) else ("original_content", "content", "evidence")
        for key in keys:
            text = str(requirement.get(key) or "")
            if _ALLOWANCE.search(text):
                alternatives.append({"value": text, "evidence": text, "explicitly_allowed": True,
                                     "page": requirement.get("page"), "position": requirement.get("position")})
    notes = review.get("notes") or []
    for note in notes if isinstance(notes, list) else [notes]:
        text = str(note.get("text") or note.get("content") or "") if isinstance(note, dict) else str(note)
        if _ALLOWANCE.search(text):
            alternatives.append({"value": text, "evidence": text, "explicitly_allowed": True})
    parameters["material"] = normalize_compression_material_parameter(original, alternatives=alternatives)
    if isinstance(review.get("drawing_summary"), dict):
        review["drawing_summary"]["material"] = parameters["material"].get("value") or ""


def validate_material_change(review: dict[str, Any], previous: dict[str, Any]) -> None:
    """Reject newly submitted out-of-catalog selections, retaining legacy values."""
    if (review.get("drawing_summary") or {}).get("spring_type") != "compression_spring":
        return
    parameters = review.setdefault("spring_parameters", {})
    item = parameters.get("material") or {}
    old = (previous.get("spring_parameters") or {}).get("material") or {}
    item = item if isinstance(item, dict) else {"value": item}
    old = old if isinstance(old, dict) else {"value": old}
    value = str(item.get("value") or "").strip()
    old_value = str(old.get("value") or "").strip()
    entry = match_material_catalog(value)
    if value != old_value:
        if entry:
            if item.get("material_id") not in (None, "", entry["id"]):
                raise ValueError("材料目录标识与当前材料不一致，请重新选择。")
            if item.get("standard_value") not in (None, "", entry["standard_value"]):
                raise ValueError("材料牌号与当前材料不一致，请重新选择。")
        source = item.get("material_selection_source")
        selected = select_compression_material(item, value, selection_source=source if source in {"manual", "ai", "drawing", "drawing_substitute"} else "manual")
        # Selection validation must not undo the explicit confirmation being saved.
        if item.get("need_human_review") is False:
            selected["need_human_review"] = False
        parameters["material"] = selected
        if item.get("material_substitution_evidence"):
            selected["material_substitution_evidence"] = deepcopy(item["material_substitution_evidence"])
        if source in {"drawing", "drawing_substitute"} and item.get("material_selection_reason"):
            selected["material_selection_reason"] = item["material_selection_reason"]
    elif entry and item.get("material_id"):
        if str(item["material_id"]) != str(entry["id"]):
            raise ValueError("材料目录标识与当前材料不一致，请重新选择。")
        if item.get("standard_value") not in (None, "", entry["standard_value"]):
            raise ValueError("材料牌号与当前材料不一致，请重新选择。")
        parameters["material"] = _apply_entry(item, entry, item.get("material_selection_source") or "drawing")
    if isinstance(parameters.get("material"), dict):
        if "raw_value" in old:
            parameters["material"]["raw_value"] = old["raw_value"]
        elif not _protected(old):
            parameters["material"]["raw_value"] = old.get("value") or item.get("raw_value") or ""
        else:
            # Historical human edits sometimes removed raw_value. A current
            # human selection is not evidence of what the drawing originally said.
            parameters["material"].pop("raw_value", None)
