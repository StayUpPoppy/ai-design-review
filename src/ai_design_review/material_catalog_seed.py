"""One-time, atomic initialization: python -m ai_design_review.material_catalog_seed."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .io_utils import read_json
from .material_catalog import MATERIAL_CATALOG_PATH
from .material_catalog_store import MaterialCatalogError, catalog_snapshot, record_item, validate_catalog
from .review_persistence import SpringMaterialRecord, database_url_from_env


def seed_material_catalog(engine: Engine, catalog: dict[str, Any]) -> dict[str, Any]:
    items = validate_catalog(catalog)
    snapshot = catalog_snapshot(items)  # Reject an entirely disabled seed, too.
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # Concurrent initializers must observe the first completed import.
            connection.execute(text("LOCK TABLE spring_materials IN EXCLUSIVE MODE"))
        with Session(bind=connection) as session:
            existing = [record_item(row) for row in session.scalars(
                select(SpringMaterialRecord).order_by(SpringMaterialRecord.sort_order, SpringMaterialRecord.id)
            ).all()]
            if existing:
                if validate_catalog({"items": existing}) == items:
                    return {"status": "unchanged", "count": len(items), "version": snapshot["version"]}
                before = {item["id"]: item for item in existing}
                after = {item["id"]: item for item in items}
                added = sorted(after.keys() - before.keys())
                removed = sorted(before.keys() - after.keys())
                changed = sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
                raise MaterialCatalogError(
                    f"已有材料与初始化数据不同，停止导入且未修改数据。新增代码={added}，"
                    f"现有额外代码={removed}，内容不同代码={changed}。请人工核对，不要清表重导。"
                )
            now = datetime.now(UTC)
            session.add_all(SpringMaterialRecord(**item, updated_at=now) for item in items)
            session.flush()
    return {"status": "imported", "count": len(items), "version": snapshot["version"]}


def main() -> int:
    database_url = database_url_from_env()
    if not database_url:
        print("初始化失败：必须设置 DATABASE_URL；此命令不会向本地 JSON 写入。", file=sys.stderr)
        return 1
    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        result = seed_material_catalog(engine, read_json(MATERIAL_CATALOG_PATH))
        action = "已导入" if result["status"] == "imported" else "内容一致，无需重复导入"
        print(f"{action}：{result['count']} 条材料，版本 {result['version']}。")
        return 0
    except (ValueError, MaterialCatalogError) as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("初始化失败：数据库连接、表结构或写入异常；请检查连接并先执行 alembic upgrade head。事务已回滚。", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
