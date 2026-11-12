"""Offline station fusion, real cached order recovery, and review save regression."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "load-identity-test"

from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.fusion import fuse_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.load_point_evidence import _collapse_saved_load_duplicates, extract_page_points, reconcile_load_points
from ai_design_review.review_persistence import ReviewPersistence


def model(label, force, height, *, evidence=None):
    evidence = evidence or f"图形载荷曲线标注 {force} N 对应高度 {height}"
    return {"field": "load_point", "source": "qwen_vision", "page": 1, "confidence": .95, "evidence": evidence,
            "value": {"label": label, "force": force, "force_unit": "N", "height": height, "height_unit": "mm",
                      "height_relation": {"kind": "absolute_height", "value": height, "unit": "mm", "evidence": evidence}}}


def local(label, force, height, x, *, scope="", segment=None):
    point = model(label, force, height)
    point.update(source="local_load_evidence", source_context={"kind": "load_graph", "force_label_inferred": True})
    point["value"]["force_evidence_verified"] = True
    point["value"]["height_relation"].update(verified=True, scope=scope, geometry_evidence={
        "load_anchor": {"x": x, "y": .2}, "datum": {"x": .1, "y": .4},
        "curve_segment": segment or [{"x": .4, "y": .2}, {"x": .6, "y": .4}],
    })
    return point


def values(candidates):
    return [point["value"] for point in fuse_candidates(candidates)["load_points"]]


def shape(points):
    return [(point["label"], point.get("height_label"), point["height"], point["force"]) for point in points]


def fusion_checks():
    single = values([model("P1", 190, 41)])[0]
    assert (single["label"], single["height_label"]) == ("F", "H")
    named = model("W7", 190, 41, evidence="工作高度 H7=41mm，W7=190N")
    assert [(p["label"], p["height_label"]) for p in values([named])] == [("W7", "H7")]
    height_only = model("", 190, 41, evidence="工作高度 H4=41mm，载荷 190N")
    height_only["value"]["height_label"] = "H4"
    assert [(p["label"], p["height_label"]) for p in values([height_only])] == [("F4", "H4")]
    assert [p["label"] for p in values([model("P1", 190, 41, evidence="P1=190N，工作高度41mm"),
                                        model("P2", 95, 51, evidence="P2=95N，工作高度51mm")])] == ["P1", "P2"]
    named = model("P1", 190, 41, evidence="P1=190N，工作高度41mm")
    original = local("P1", 190, 41, .4)
    original["source_context"]["force_label_inferred"] = False
    assert shape(values([named, {**named, "source": "werk24_semantic"}, original])) == [("P1", "H1", 41, 190)]

    a, b = local("F1", 190, 41, .4), local("F2", 95, 51, .6)
    draft = model("P2", .19, 4.1)
    draft["value"].update(force_unit="kN", height_unit="cm")
    draft["value"]["height_relation"]["unit"] = "cm"
    assert shape(values([model("P1", 95, 51), draft, b, a])) == [("F1", "H1", 41, 190), ("F2", "H2", 51, 95)]
    assert len(values([a, local("F2", 190, 41, .6), draft])) == 3
    assert len(values([local("F1", 190, 41, .4, scope="a"), local("F2", 190, 41, .4, scope="b")])) == 2
    isolated = local("F2", 95, 51, .8, segment=[{"x": .7, "y": .2}, {"x": .8, "y": .4}])
    assert len(values([a, isolated, draft])) == 3
    dispute = model("P2", 200, 42)
    dispute["value"]["height_relation"]["graphic_hint"] = {"load_contact": {"x": .4, "y": .2}, "datum": {"x": .1, "y": .4}}
    fused = values([a, dispute])
    assert len(fused) == 1 and fused[0]["load_force_conflict"] and fused[0]["load_height_conflict"]
    assert fused[0]["force_alternatives"] == [190, 200]
    table = {"page": 1, "width": 300, "height": 200, "lines": [], "texts": [
        {"text": text, "bbox": [x, y, x + width, y + 14]}
        for text, x, y, width in (("WORK LENGTH", 12, 30, 100), ("41", 166, 30, 20), ("mm", 230, 30, 20),
                                   ("LOAD", 12, 50, 50), ("190", 164, 50, 24), ("N", 230, 50, 12))]}
    verified = extract_page_points(table, hints=[{"label": "", "force": 190, "force_unit": "N"}])
    assert [(p["label"], p["height_label"], p["height_relation"]["verified"]) for p in verified] == [("F", "H", True)]


def archived(candidate, point_id):
    return {**candidate["value"], "page": candidate["page"], "source": [candidate["source"]],
            "evidence": candidate["evidence"], "source_context": candidate.get("source_context", {}),
            "load_point_id": point_id, "need_human_review": True}


def protection_checks():
    original = archived(local("F1", 190, 41, .4), "original")
    duplicate = archived(model("P2", 190, 41), "duplicate")
    dependent = archived(model("P3", 220, 34), "dependent")
    dependent["height_relation"].update(kind="incremental_deflection", base_point_id="duplicate", base_label="P2")
    points = [original, duplicate, dependent]
    _collapse_saved_load_duplicates({}, points)
    assert [p["load_point_id"] for p in points] == ["original", "dependent"]
    assert dependent["height_relation"]["base_point_id"] == "original"
    dependent["height_relation"]["base_point_id"] = "duplicate"
    for protected_id in ("duplicate", "original", "dependent"):
        points = deepcopy([original, duplicate, dependent])
        _collapse_saved_load_duplicates({"change_history": [{"event_type": "load_point_value_updated",
            "metadata": {"load_point_id": protected_id}}]}, points)
        assert len(points) == 3
    points = deepcopy([original, duplicate])
    _collapse_saved_load_duplicates({"manual_confirmations": {"load_point_duplicate": {"confirmed": True}}}, points)
    assert len(points) == 2


def replay_real_order():
    cache = ROOT / "outputs/load-identity-qa"
    if not (cache / "review.json").is_file() or not (cache / "inputs").is_dir():
        return
    payload = json.loads((cache / "candidates.json").read_bytes())
    raw = [c for c in payload["candidates"] if c.get("field") == "load_point"]
    assert [p["label"] for p in values(raw)] == ["F1", "F2"]
    review = json.loads((cache / "review.json").read_bytes())
    expected = [("F1", "H1", 41, 190), ("F2", "H2", 51, 95)]
    original_ids = [p["load_point_id"] for p in review["spring_parameters"]["load_points"] if p["label"] in {"F1", "F2"}]

    with tempfile.TemporaryDirectory(prefix="load-identity-") as directory:
        root = Path(directory)
        job = root / "job"
        shutil.copytree(cache / "inputs", job / "inputs")
        shutil.copyfile(cache / "candidates.json", job / "candidates.json")
        deleted = deepcopy(review)
        removed = next(p for p in deleted["spring_parameters"]["load_points"] if p["label"] == "P2")
        deleted["spring_parameters"]["load_points"] = [p for p in deleted["spring_parameters"]["load_points"] if p["label"] not in {"P2", "F1"}]
        deleted.setdefault("change_history", []).append({"event_type": "load_point_deleted", "before_state": removed})
        reconcile_load_points(deleted, job)
        assert shape(deleted["spring_parameters"]["load_points"]) == [expected[1]]
        repo = ReviewPersistence(f"sqlite+pysqlite:///{root/'review.db'}")
        repo.create_schema_for_testing()
        repo.create_review("job", review, file_info={"kind": "image"}, artifact_dir=str(job), owner={"user_id": "load-identity-test"})
        with (patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", repo),
              patch.object(api, "verify_review_roughness"), patch("ai_design_review.diameter_evidence.reconcile_diameter_review"),
              patch("ai_design_review.load_point_evidence.raster_pages", side_effect=AssertionError("Reuse saved load evidence")), TestClient(api.app) as client):
            response = client.get("/api/reviews/job")
            assert response.status_code == 200, response.text
            loaded = response.json()
            assert shape(loaded["spring_parameters"]["load_points"]) == expected
            assert [p["load_point_id"] for p in loaded["spring_parameters"]["load_points"]] == original_ids
            assert len(repo.get_review("job")["review"]["spring_parameters"]["load_points"]) == 4
            stale = deepcopy(review)
            stale["spring_parameters"]["load_points"][-1]["force"] = 191
            assert client.patch("/api/reviews/job", json={"review": stale, "expected_revision": 1}).status_code == 409
            saved = client.patch("/api/reviews/job", json={"review": loaded, "expected_revision": 1})
            assert saved.status_code == 200, saved.text
            assert any(e["event_type"] == "load_height_evidence_reconciled" for e in repo.list_change_events("job"))
            reopened = client.get("/api/reviews/job").json()
            assert shape(reopened["spring_parameters"]["load_points"]) == expected
            assert build_generation_parameter_package(reopened)["generation_parameters"]["load_points"] == []
            for p in reopened["spring_parameters"]["load_points"]:
                p["need_human_review"] = False
            saved = client.patch("/api/reviews/job", json={"review": reopened, "expected_revision": saved.json()["review_revision"]})
            assert saved.status_code == 200, saved.text
            confirmed = client.get("/api/reviews/job").json()
            exported = build_generation_parameter_package(confirmed)["generation_parameters"]["load_points"]
            assert [(p["label"], p["height"]["value"], p["force"]["value"]) for p in exported] == [("F1", 41, 190), ("F2", 51, 95)]
        repo.dispose()
    print("PASS 2426GH-21 actual cache, read-only recovery, stable IDs, stale save, audit, reopen and confirmed generation package")


if __name__ == "__main__":
    fusion_checks()
    protection_checks()
    replay_real_order()
    print("PASS station identity, default/original labels, units, ambiguous or distinct positions, conflict and history protection")
