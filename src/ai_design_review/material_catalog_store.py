"""Validation and read-only snapshots for the shared spring-material catalog."""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .material_terms import normalize_material_key
from .review_persistence import SpringMaterialRecord

PROPERTY_FIELDS = (
    "tensile_strength_mpa", "shear_modulus_mpa", "elastic_modulus_mpa",
    "density_g_cm3", "allowable_shear_stress_mpa", "allowable_stress_coefficient",
)
RECORD_FIELDS = (
    "id", "display_name", "standard_value", "aliases", *PROPERTY_FIELDS,
    "source", "source_display_name", "source_row", "sort_order", "enabled",
)
DESCRIPTION = "公司压缩弹簧材料目录；材料属性为表内固定参考值，不作温度、线径或热处理修正。"


class MaterialCatalogError(RuntimeError):
    pass


def validate_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the entire input before opening an import transaction."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list) or not catalog["items"]:
        raise ValueError("公司材料目录不能为空。")
    ids: set[str] = set()
    grades: dict[str, str] = {}
    result = []
    for index, original in enumerate(catalog["items"]):
        if not isinstance(original, dict):
            raise ValueError("公司材料目录条目必须为对象。")
        item = deepcopy(original)
        material_id = str(item.get("id") or "").strip()
        if not material_id or len(material_id) > 64 or material_id in ids:
            raise ValueError(f"公司材料目录包含无效或重复代码：{material_id}。")
        ids.add(material_id)
        item["id"] = material_id
        for field in ("display_name", "standard_value"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError(f"材料 {material_id} 的 {field} 无效。")
            item[field] = value.strip()
        aliases = item.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ValueError(f"材料 {material_id} 的别名必须为非空字符串列表。")
        item["aliases"] = list(dict.fromkeys(alias.strip() for alias in aliases))
        for alias in [item["display_name"], item["standard_value"], *item["aliases"]]:
            key = normalize_material_key(alias)
            if not key or (key in grades and grades[key] != material_id):
                raise ValueError(f"材料 {material_id} 的名称或别名与其他材料重复：{alias}。")
            grades[key] = material_id
        for field in PROPERTY_FIELDS:
            value = item.get(field)
            if value is None and field not in {"shear_modulus_mpa", "density_g_cm3"}:
                item[field] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"材料 {material_id} 的 {field} 必须为有限正数。")
            item[field] = float(value)
        item["source"] = item.get("source", catalog.get("source", ""))
        item["source_display_name"] = item.get("source_display_name", item["display_name"])
        for field in ("source", "source_display_name"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f"材料 {material_id} 缺少来源信息。")
        if len(item["source_display_name"]) > 256:
            raise ValueError(f"材料 {material_id} 的来源名称过长。")
        item["source_row"] = item.get("source_row")
        if item["source_row"] is not None and (type(item["source_row"]) is not int or item["source_row"] <= 0):
            raise ValueError(f"材料 {material_id} 的来源行号无效。")
        item["sort_order"] = item.get("sort_order", index)
        item["enabled"] = item.get("enabled", True)
        if type(item["sort_order"]) is not int or item["sort_order"] < 0 or type(item["enabled"]) is not bool:
            raise ValueError(f"材料 {material_id} 的排序或启用状态无效。")
        result.append({field: item[field] for field in RECORD_FIELDS})
    return sorted(result, key=lambda item: (item["sort_order"], item["id"]))


def catalog_snapshot(items: list[dict[str, Any]]) -> dict[str, Any]:
    active = [item for item in items if item["enabled"]]
    if not active:
        raise MaterialCatalogError("数据库材料库没有启用的材料，请先执行材料初始化命令。")
    payload = json.dumps(active, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "version": f"company-materials/sha256:{digest}",
        "source": "；".join(dict.fromkeys(item["source"] for item in active)),
        "description": DESCRIPTION,
        "items": active,
    }


def record_item(record: SpringMaterialRecord) -> dict[str, Any]:
    return {field: deepcopy(getattr(record, field)) for field in RECORD_FIELDS}


def load_database_catalog(database_url: str) -> dict[str, Any]:
    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with Session(engine) as session:
            rows = session.scalars(select(SpringMaterialRecord).where(SpringMaterialRecord.enabled.is_(True))
                                   .order_by(SpringMaterialRecord.sort_order, SpringMaterialRecord.id)).all()
            if not rows:
                raise MaterialCatalogError("数据库材料库为空，请先执行 python -m ai_design_review.material_catalog_seed。")
            return catalog_snapshot(validate_catalog({"items": [record_item(row) for row in rows]}))
    except SQLAlchemyError as exc:
        # Do not include connection URLs/credentials in client-facing errors.
        raise MaterialCatalogError(
            "数据库材料库读取失败，请检查数据库连接，并先执行 alembic upgrade head 和材料初始化命令。"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()
