"""Isolated material migration/import/calculation tests; never use the deployment DB."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_design_review.io_utils import read_json
from ai_design_review.material_catalog import MATERIAL_CATALOG_PATH, load_material_catalog, material_catalog_matches, match_material_catalog
from ai_design_review.material_catalog_seed import seed_material_catalog
from ai_design_review.material_catalog_store import MaterialCatalogError, PROPERTY_FIELDS, catalog_snapshot, validate_catalog
from ai_design_review.review_persistence import Base, SpringMaterialRecord
from ai_design_review.standardizers.design_checks import calculate_design_checks
from ai_design_review.standardizers.stiffness import calculate_compression_spring_rate

ADDED_GRADES = {"60Si2CrVAT", "ASTM A229", "GB/T 4357-2022-DH", "ASTM A313 Type 302", "ASTM A401"}


class MaterialDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="material-db-")
        self.url = "sqlite:///" + str(Path(self.directory.name) / "materials.db").replace("\\", "/")
        self.engine = create_engine(self.url)
        SpringMaterialRecord.__table__.create(self.engine)
        self.seed = read_json(MATERIAL_CATALOG_PATH)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": self.url})
        self.environment.start()
        load_material_catalog.cache_clear()

    def tearDown(self):
        load_material_catalog.cache_clear()
        self.environment.stop()
        self.engine.dispose()
        self.directory.cleanup()

    def count(self):
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(SpringMaterialRecord))

    def test_import_restart_noop_and_source(self):
        self.assertEqual(seed_material_catalog(self.engine, self.seed)["status"], "imported")
        first = load_material_catalog()
        self.assertEqual(len(first["items"]), 108)
        self.assertEqual(first["version"], self.seed["version"])
        with Session(self.engine) as session:
            original_time = session.get(SpringMaterialRecord, "1").updated_at
        self.assertEqual(seed_material_catalog(self.engine, self.seed)["status"], "unchanged")
        with Session(self.engine) as session:
            self.assertEqual(session.get(SpringMaterialRecord, "1").updated_at, original_time)
            self.assertEqual(session.get(SpringMaterialRecord, "10").source_display_name, "lnconelX750")
            self.assertEqual(session.get(SpringMaterialRecord, "11").display_name, "70#")
        load_material_catalog.cache_clear()
        self.assertEqual(load_material_catalog(), first)
        output = subprocess.check_output([sys.executable, "-c", "from ai_design_review.material_catalog import load_material_catalog; import json; print(json.dumps(load_material_catalog()))"],
                                         cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, text=True, encoding="utf-8")
        self.assertEqual(json.loads(output), first)

    def test_invalid_data_and_optional_nulls(self):
        for field in ("shear_modulus_mpa", "density_g_cm3"):
            for invalid in (None, 0, -1, True, "78000", float("inf"), float("nan")):
                with self.subTest(field=field, value=invalid):
                    seed = deepcopy(self.seed)
                    seed["items"][-1][field] = invalid
                    with self.assertRaises(ValueError):
                        seed_material_catalog(self.engine, seed)
                    self.assertEqual(self.count(), 0)
        for field in set(PROPERTY_FIELDS) - {"shear_modulus_mpa", "density_g_cm3"}:
            seed = deepcopy(self.seed)
            seed["items"][0][field] = None
            self.assertIsNone(validate_catalog(seed)[0][field])
            seed["items"][0][field] = -1
            with self.assertRaises(ValueError):
                seed_material_catalog(self.engine, seed)
        seed_material_catalog(self.engine, self.seed)
        self.assertTrue(any(item["tensile_strength_mpa"] is None for item in load_material_catalog()["items"]))

    def test_duplicate_code_name_alias_and_empty(self):
        for field in ("id", "display_name", "standard_value", "aliases"):
            seed = deepcopy(self.seed)
            seed["items"][-1][field] = deepcopy(seed["items"][0][field])
            with self.assertRaises(ValueError, msg=field):
                seed_material_catalog(self.engine, seed)
            self.assertEqual(self.count(), 0)
        with self.assertRaises(ValueError):
            seed_material_catalog(self.engine, {"items": []})

    def test_conflict_does_not_write(self):
        seed_material_catalog(self.engine, self.seed)
        before = load_material_catalog()
        altered = deepcopy(self.seed)
        altered["items"][-1]["density_g_cm3"] += 1
        with self.assertRaisesRegex(MaterialCatalogError, "内容不同代码"):
            seed_material_catalog(self.engine, altered)
        load_material_catalog.cache_clear()
        self.assertEqual(load_material_catalog(), before)

    def test_append_selected_codes_and_repeat(self):
        original = {**self.seed, "items": [item for item in self.seed["items"] if item["display_name"] not in ADDED_GRADES]}
        added_ids = [item["id"] for item in self.seed["items"] if item["display_name"] in ADDED_GRADES]
        seed_material_catalog(self.engine, original)
        self.assertEqual(self.count(), 103)
        with Session(self.engine) as session:
            original_time = session.get(SpringMaterialRecord, "1").updated_at
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        command = [sys.executable, "-m", "ai_design_review.material_catalog_seed", "--append", *added_ids]
        for expected in ("已追加 5 条", "内容一致"):
            result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
        self.assertEqual(self.count(), 108)
        with Session(self.engine) as session:
            self.assertEqual(session.get(SpringMaterialRecord, "1").updated_at, original_time)
        self.assertEqual(load_material_catalog()["version"], self.seed["version"])
        self.assertEqual(seed_material_catalog(self.engine, self.seed)["status"], "unchanged")

    def test_append_conflict_does_not_add_any_row(self):
        original = {**self.seed, "items": [item for item in self.seed["items"] if item["display_name"] not in ADDED_GRADES]}
        added_ids = [item["id"] for item in self.seed["items"] if item["display_name"] in ADDED_GRADES]
        seed_material_catalog(self.engine, original)
        with self.assertRaisesRegex(ValueError, "缺少材料代码"):
            seed_material_catalog(self.engine, self.seed, append_ids=[*added_ids, "unknown"])
        with Session(self.engine) as session, session.begin():
            current = session.get(SpringMaterialRecord, "1")
            current.aliases = [*current.aliases, "ASTM A401"]
        with self.assertRaisesRegex(ValueError, "与其他材料重复"):
            seed_material_catalog(self.engine, self.seed, append_ids=added_ids)
        self.assertEqual(self.count(), 103)
        with Session(self.engine) as session, session.begin():
            current = session.get(SpringMaterialRecord, "1")
            current.aliases = original["items"][0]["aliases"]
            current.shear_modulus_mpa += 1
        with self.assertRaisesRegex(MaterialCatalogError, "内容不同"):
            seed_material_catalog(self.engine, self.seed, append_ids=["1", *added_ids])
        self.assertEqual(self.count(), 103)

    def test_database_failure_rolls_back_every_row(self):
        def fail_insert(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("INSERT INTO SPRING_MATERIALS"):
                raise SQLAlchemyError("injected write failure")
        event.listen(self.engine, "after_cursor_execute", fail_insert)
        try:
            with self.assertRaises(SQLAlchemyError):
                seed_material_catalog(self.engine, self.seed)
        finally:
            event.remove(self.engine, "after_cursor_execute", fail_insert)
        self.assertEqual(self.count(), 0)
        self.assertEqual(seed_material_catalog(self.engine, self.seed)["status"], "imported")

    def test_database_is_authoritative_and_snapshot_is_stable(self):
        seed_material_catalog(self.engine, self.seed)
        first = load_material_catalog()
        with Session(self.engine) as session, session.begin():
            session.get(SpringMaterialRecord, "4").shear_modulus_mpa = 70000
            session.get(SpringMaterialRecord, "5").enabled = False
        self.assertEqual(load_material_catalog(), first, "Catalog changes require process restart")
        load_material_catalog.cache_clear()
        current = load_material_catalog()
        self.assertNotEqual(current["version"], first["version"])
        self.assertEqual(match_material_catalog("SUS304")["shear_modulus_mpa"], 70000)
        self.assertIsNone(match_material_catalog("SUS316"))
        rate = calculate_compression_spring_rate({"material": {"value": "SUS316"}, "wire_diameter": {"value": 2}, "mean_diameter": {"value": 18}, "active_coils": {"value": 10}})
        self.assertEqual(rate["status"], "material_not_configured", "Disabled materials must not use the legacy property JSON")

    def test_no_fallback_for_empty_missing_invalid_or_unavailable_db(self):
        with self.assertRaises(MaterialCatalogError):
            load_material_catalog()
        SpringMaterialRecord.__table__.drop(self.engine)
        with self.assertRaises(MaterialCatalogError):
            load_material_catalog()
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:////invalid-material-test-directory/nonexistent.db"}):
            with self.assertRaises(MaterialCatalogError):
                load_material_catalog()
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            self.assertEqual(len(load_material_catalog()["items"]), 108)
        SpringMaterialRecord.__table__.create(self.engine)
        seed_material_catalog(self.engine, self.seed)
        with Session(self.engine) as session, session.begin():
            session.get(SpringMaterialRecord, "4").aliases = ["SWPB"]
        with self.assertRaises(ValueError):
            load_material_catalog()

    def test_all_grades_aliases_overlaps_and_independent_mentions(self):
        seed_material_catalog(self.engine, self.seed)
        for item in load_material_catalog()["items"]:
            for text in (item["display_name"], item["standard_value"], *item["aliases"]):
                self.assertEqual(match_material_catalog(text)["id"], item["id"], text)
        for text, names in (
            ("材料：SUS304-WPB", ["SUS304-WPB"]),
            ("SUS316/SUS316L", ["SUS316/SUS316L"]),
            ("材料 SUS316/SUS316L，表面喷丸", ["SUS316/SUS316L"]),
            ("SUS304-WPB 或 SUS304", ["SUS304", "SUS304-WPB"]),
            ("SUS316/SUS316L 或 SUS316", ["SUS316", "SUS316/SUS316L"]),
            ("60Si2MnA", ["60Si2MnA"]),
            ("60Si2Mn 或 60Si2MnA", ["60Si2Mn", "60Si2MnA"]),
        ):
            self.assertEqual([item["display_name"] for item in material_catalog_matches(text)], names, text)

    def test_original_15_and_new_material_calculations(self):
        seed_material_catalog(self.engine, self.seed)
        original_g = [78000, 78000, 78000, 71500, 71500, 73500, 78000, 78000, 78000, 79000, 79000, 79000, 76000, 75500, 77200]
        original_rho = [7.85, 7.85, 7.85, 7.93, 8, 7.93, 7.85, 7.85, 7.85, 8.28, 7.85, 7.85, 7.8, 7.93, 8.24]
        for item in load_material_catalog()["items"]:
            params = {field: {"value": value, "need_human_review": False} for field, value in
                      {"material": item["display_name"], "wire_diameter": 2, "mean_diameter": 18, "free_length": 40,
                       "total_coils": 12, "active_coils": 10, "pitch": 3.7, "end_type": "两端并紧", "end_grinding": "两端磨削", "support_coils": 1}.items()}
            checks = calculate_design_checks(params)
            self.assertAlmostEqual(checks["metrics"]["theoretical_spring_rate"]["value"], item["shear_modulus_mpa"] * 2**4 / (8 * 18**3 * 10), places=4)
            expected_mass = math.pi * 2**2 / 4 * math.hypot(math.pi * 18, 3.7) * 12 * item["density_g_cm3"] * 1e-6
            self.assertAlmostEqual(checks["metrics"]["unit_mass"]["value"], expected_mass, places=5)
            if int(item["id"]) <= 15:
                index = int(item["id"]) - 1
                self.assertEqual(item["shear_modulus_mpa"], original_g[index])
                self.assertEqual(item["density_g_cm3"], original_rho[index])
        self.assertEqual(match_material_catalog("60Si2MnA")["shear_modulus_mpa"], 78500)
        self.assertEqual(match_material_catalog("60Si2Mn")["shear_modulus_mpa"], 78000)

    def test_latest_migration_and_cli(self):
        SpringMaterialRecord.__table__.drop(self.engine)
        spec = importlib.util.spec_from_file_location("material_migration", ROOT / "migrations/versions/20261108_01_spring_materials.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        self.assertEqual({column["name"] for column in inspect(self.engine).get_columns("spring_materials")}, set(SpringMaterialRecord.__table__.columns.keys()))
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        for expected in ("已导入", "内容一致"):
            result = subprocess.run([sys.executable, "-m", "ai_design_review.material_catalog_seed"], cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
        result = subprocess.run([sys.executable, "-m", "ai_design_review.material_catalog_seed"], cwd=ROOT, env={**environment, "DATABASE_URL": ""}, capture_output=True)
        self.assertEqual(result.returncode, 1)
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
        self.assertNotIn("spring_materials", inspect(self.engine).get_table_names())

    def test_api_startup_worker_and_frozen_generation(self):
        from fastapi.testclient import TestClient
        from ai_design_review import api, recognition_worker
        from ai_design_review.generation_readiness import build_generation_parameter_package
        from ai_design_review.review_persistence import ReviewPersistence
        from ai_design_review.solidworks import build_solidworks_command
        from test_material_catalog_generation import ready_review
        from threading import Event

        store = ReviewPersistence(database_url=self.url)
        store.create_schema_for_testing()
        seed_material_catalog(self.engine, self.seed)
        try:
            with patch.dict(os.environ, {"AI_REVIEW_IDENTITY_MODE": "mock", "AI_REVIEW_MOCK_USER_ID": "material-db-test"}), \
                 patch.object(api, "REVIEW_PERSISTENCE", store), \
                 patch.object(api, "ragflow_runtime_status", return_value={"status": "not_configured"}):
                with TestClient(api.app) as client:
                    response = client.get("/api/material-catalog")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), load_material_catalog())
                    self.assertEqual(len(response.json()["items"]), 108)
                stopped = Event()
                stopped.set()
                with patch.object(recognition_worker, "REVIEW_PERSISTENCE", store), \
                     patch.object(recognition_worker, "STOP_EVENT", stopped), \
                     patch.object(recognition_worker, "load_material_catalog", wraps=load_material_catalog) as load:
                    recognition_worker.RecognitionWorker().run()
                    load.assert_called_once()

            review = ready_review("60Si2MnA")
            original = deepcopy(review)
            frozen = build_generation_parameter_package(review)
            material = frozen["derived_parameters"]["solidworks_design_checks"]["material_properties"]
            self.assertEqual(material["shear_modulus_mpa"], 78500)
            self.assertEqual(material["density_g_cm3"], 7.85)
            self.assertEqual(frozen["derived_parameters"]["solidworks_design_checks"]["material_catalog_version"], load_material_catalog()["version"])
            for field, value in original["spring_parameters"].items():
                self.assertEqual(review["spring_parameters"][field], value, "Packaging does not overwrite confirmed inputs")
            frozen_json = json.dumps(frozen, ensure_ascii=False, sort_keys=True)
            command = build_solidworks_command("1000000042", frozen, review)
            with Session(self.engine) as session, session.begin():
                session.get(SpringMaterialRecord, "86").shear_modulus_mpa = 70000
            load_material_catalog.cache_clear()
            review["spring_parameters"]["material"]["value"] = "SUS304"
            self.assertEqual(build_solidworks_command("1000000042", frozen, review), command, "Retry retains frozen calculations and material")
            self.assertEqual(json.dumps(frozen, ensure_ascii=False, sort_keys=True), frozen_json)
        finally:
            store.dispose()


if __name__ == "__main__":
    unittest.main(verbosity=2)
