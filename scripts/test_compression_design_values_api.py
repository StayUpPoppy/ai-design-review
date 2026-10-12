from __future__ import annotations

import copy
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "design-values-test"
from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.io_utils import write_json
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.standardizers.design_checks import refresh_design_checks
from ai_design_review.standardizers.compression import apply_formula_compression_solid_height


def main():
    fixture = json.loads((ROOT / "data/test/compression_design_checks.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="design-values-") as directory:
        root = Path(directory)
        job = root / "test-job"
        job.mkdir()
        write_json(job / "review.json", fixture["base"])
        write_json(job / "owner.json", {"user_id":"design-values-test"})
        original = (job / "review.json").read_bytes()
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")), TestClient(api.app) as client:
            catalog = client.get("/api/material-catalog").json()
            assert catalog["items"][3]["density_g_cm3"] == 7.93
            response = client.get("/api/reviews/test-job")
            assert response.status_code == 200, response.text
            loaded = response.json()
            assert loaded["spring_parameters"]["pitch"]["value"] == 3.3
            assert math.isclose(loaded["design_checks"]["metrics"]["unit_mass"]["value"], .01693420942045807)
            assert (job / "review.json").read_bytes() == original, "GET only computes the view"
            loaded["design_checks"] = {"metrics":{"unit_mass":{"value":1000000}}}
            loaded["spring_parameters"]["free_length"]["value"] = 40
            assert client.patch("/api/reviews/test-job", json={"review":loaded}).status_code == 200
            saved = client.get("/api/reviews/test-job").json()
            assert saved["spring_parameters"]["pitch"]["value"] == 3.7
            assert saved["design_checks"]["metrics"]["unit_mass"]["value"] < 1
            assert saved["spring_parameters"]["load_points"][2]["force"] is None
            disk = json.loads((job / "review.json").read_text(encoding="utf-8"))
            assert disk["design_checks"] == saved["design_checks"]
            pitch = saved["spring_parameters"]["pitch"]
            pitch.update(need_human_review=False, source=["formula_calculation","human_confirmed"])
            assert client.patch("/api/reviews/test-job", json={"review":saved}).status_code == 200
            saved["spring_parameters"]["free_length"]["value"] = 42
            assert client.patch("/api/reviews/test-job", json={"review":saved}).status_code == 200
            saved = client.get("/api/reviews/test-job").json()
            assert saved["spring_parameters"]["pitch"]["value"] == 3.7
            assert saved["spring_parameters"]["pitch"]["derived_value_stale"]
            assert saved["design_checks"]["metrics"]["unit_mass"]["value"] is None
            saved["spring_parameters"]["pitch"].update(value="", source=["human_edited"],need_human_review=True)
            assert client.patch("/api/reviews/test-job", json={"review":saved}).status_code == 200
            reopened = client.get("/api/reviews/test-job").json()
            assert reopened["spring_parameters"]["pitch"]["value"] == ""
            assert reopened["design_checks"]["metrics"]["unit_mass"]["value"] is None
            order = copy.deepcopy(fixture["base"])
            case = next(case for case in fixture["cases"] if case["name"] == "order2-user-confirmed-counts")
            for field, value in case["overrides"].items():
                if isinstance(value, dict):
                    order["spring_parameters"].setdefault(field, {}).update(value)
                else:
                    order["spring_parameters"][field] = value
            order_job = root / "order2-inference"
            order_job.mkdir()
            write_json(order_job / "review.json", order)
            write_json(order_job / "owner.json", {"user_id":"design-values-test"})
            order = client.get("/api/reviews/order2-inference").json()
            support = order["spring_parameters"]["support_coils"]
            assert support["value"] == 1 and support["need_human_review"]
            assert support["source_fields"] == ["total_coils", "active_coils", "end_type"]
            assert order["spring_parameters"]["pitch"]["value"] == 4.075
            assert math.isclose(order["design_checks"]["metrics"]["solid_stress"]["value"], 161.67436065316636)
            assert math.isclose(order["design_checks"]["metrics"]["unit_mass"]["value"], .009598078574462507)
            assert order["spring_parameters"]["total_coils"]["value"] == 6
            assert order["spring_parameters"]["active_coils"]["value"] == 4
            assert client.patch("/api/reviews/order2-inference", json={"review":order}).status_code == 200
            order_reopened = client.get("/api/reviews/order2-inference").json()
            assert order_reopened["design_checks"] == order["design_checks"]
            book = copy.deepcopy(fixture["base"])
            case = next(case for case in fixture["cases"] if case["name"] == "book-order2-baseline")
            for field, value in case["overrides"].items():
                if isinstance(value, dict):
                    book["spring_parameters"].setdefault(field, {}).update(value)
                else:
                    book["spring_parameters"][field] = value
            book["spring_parameters"]["end_grinding"]["value"] = "两端不磨削"
            apply_formula_compression_solid_height(book["spring_parameters"])
            book["spring_parameters"]["solid_height"].update(need_human_review=False, source=["formula_calculation", "human_confirmed"])
            book_job = root / "book-model"
            book_job.mkdir()
            write_json(book_job / "review.json", book)
            write_json(book_job / "owner.json", {"user_id":"design-values-test"})
            loaded = client.get("/api/reviews/book-model").json()
            assert loaded["spring_parameters"]["solid_height"]["value"] == 9
            assert loaded["spring_parameters"]["solid_height"]["legacy_reference_limit"]["value"] == 10.175
            assert loaded["spring_parameters"]["solid_height"]["need_human_review"]
            loaded["spring_parameters"]["end_grinding"]["value"] = "两端磨削"
            loaded["design_checks"] = {"version":"old", "metrics":{"solid_stress":{"value":0}}}
            assert client.patch("/api/reviews/book-model", json={"review":loaded}).status_code == 200
            reopened = client.get("/api/reviews/book-model").json()
            height = reopened["spring_parameters"]["solid_height"]
            assert height["value"] == 6.3 and not height["derived_value_stale"]
            assert height["value_kind"] == "nominal_estimate" and height["need_human_review"]
            assert height["legacy_reference_limit"]["value"] == 10.175
            checks = reopened["design_checks"]
            assert checks["version"] == "compression-design-v2"
            assert checks["metrics"]["solid_height_used"]["value"] == 6.3
            assert math.isclose(checks["metrics"]["solid_stress"]["value"], 451.26689676793944)
            original = (book_job / "review.json").read_bytes()
            assert client.get("/api/reviews/book-model").json()["design_checks"] == checks
            assert (book_job / "review.json").read_bytes() == original
    print("compression design API: legacy load, independent read, authoritative save, reopen, confirmed stale and human blank passed")


if __name__ == "__main__":
    main()
