"""Temporary DB and mock SW only; no external recognition/translation."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, create_request
from test_company_surface_mapping import review_fixture, source_review_fixture, company_id, RAW, CHINESE
from fastapi.testclient import TestClient
from ai_design_review import standard_selector
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_persistence import GenerationJobRecord
from ai_design_review.generation_readiness import build_generation_parameter_package


def main():
    original = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness, standard_selector.standard_references, api._post_solidworks_command
    api.verify_review_roughness = lambda *a, **k: None
    standard_selector.standard_references = lambda *a, **k: []
    submissions = []
    api._post_solidworks_command = lambda url, payload, **kwargs: submissions.append(deepcopy(payload))
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api.REVIEW_PERSISTENCE = repo = ReviewPersistence(f"sqlite+pysqlite:///{root / 'surface.db'}")
            repo.create_schema_for_testing(); api.API_RUN_ROOT = root / "runs"; api.API_RUN_ROOT.mkdir()
            repo.create_review("surface", review_fixture(), owner=OWNER)
            linked_fixture = source_review_fixture()
            for v in linked_fixture["technical_requirements"][:-1]: v["need_human_review"] = False
            repo.create_review("linked", linked_fixture, owner=OWNER)
            legacy = review_fixture(); legacy["technical_requirements"] = [{"requirement_id": "legacy", "type": "process", "content": RAW, "need_human_review": False}]
            repo.create_review("legacy", legacy, owner=OWNER)
            with patch("ai_design_review.surface_terms._decide_with_llm", side_effect=AssertionError("No model calls")), TestClient(api.app) as client:
                response = client.get("/api/surface-treatment-catalog")
                assert response.status_code == 200, response.text
                assert len(response.json()["items"]) == 49
                assert client.post("/api/surface-treatment-catalog", json={}).status_code == 405
                # Old orders acquire only a read projection, not automatic text
                # or confirmation changes. An ordinary save persists verified IDs.
                linked = client.get("/api/reviews/linked").json()
                assert "source_requirement_ids" not in linked["technical_requirements"][0]["surface_mapping"]
                original_notes = deepcopy(linked["technical_requirements"])
                linked_package = client.get("/api/reviews/linked/generation-package")
                assert linked_package.status_code == 200, linked_package.text
                assert "Fe/Ep" not in linked_package.json()["parameter_package"]["solidworks_preview"]["technicalRequirements"]["技术要求"]
                linked["technical_requirements"][0]["surface_mapping"]["source_requirement_ids"] = ["heat"]
                saved_link = client.patch("/api/reviews/linked", json={"review": linked, "expected_revision": linked["review_revision"]})
                assert saved_link.status_code == 200, saved_link.text
                linked = client.get("/api/reviews/linked").json()
                assert linked["technical_requirements"][0]["surface_mapping"]["source_requirement_ids"] == ["surface-ocr"]
                assert linked["technical_requirements"][0]["need_human_review"] is False
                assert linked["technical_requirements"][-1] == original_notes[-1]
                assert any(e["event_type"] == "surface_requirement_sources_linked" for e in linked.get("change_history", []))
                old = client.get("/api/reviews/legacy").json()
                assert old["technical_requirements"][0]["content"] == RAW
                assert old["technical_requirements"][0]["need_human_review"] is False
                assert "surface_mapping" not in old["technical_requirements"][0]
                check_review = review_fixture()
                check_review["technical_requirements"] = [
                    {"requirement_id": key, "type": "surface", "content": text, "original_content": text,
                     "need_human_review": True, "surface_mapping": {
                         "catalog_ids": [], "selection_mode": "auto", "conversion_status": "needs_input",
                         "verification": {"status": "uncertain", "readings": [{"text": reading} for reading in readings]}
                     }}
                    for key, text, readings in [
                        ("shot", "表面处理：抛丸。", ["5. 抛丸。", "5. 混丸。"]),
                        ("paint", "涂清漆。", ["6. 涂漆。", "6. 涂清漆。"]),
                        ("zinc", "表面处理：表面处理 镀锌五彩", ["镀锌五彩"]),
                        ("conflict", "喷丸。", ["5. 抛丸。", "5. 喷丸。"]),
                        ("heading", "表面处理：表面处理", []),
                    ]
                ]
                repo.create_review("surface-check", check_review, owner=OWNER)
                check_path = "/api/reviews/surface-check"
                check = client.get(check_path).json()
                assert [row["content"] for row in check["technical_requirements"]] == [row["content"] for row in check_review["technical_requirements"]]
                stale = deepcopy(check)
                conflict_note = stale["technical_requirements"][3]
                conflict_note["need_human_review"] = False
                conflict_note.pop("surface_mapping")
                bulk_conflict = {"event_type": "safe_fields_confirmed", "metadata": {"fields": ["technical_requirements.conflict"]}}
                rejected = client.patch(check_path, json={"review": stale, "expected_revision": check["review_revision"], "events": [bulk_conflict]})
                assert rejected.status_code == 422 and "读数有冲突" in rejected.json()["detail"]["message"], rejected.text
                for row in check["technical_requirements"][:3]:
                    row["need_human_review"] = False
                ids = ["technical_requirements." + row["requirement_id"] for row in check["technical_requirements"][:3]]
                bulk = {"event_type": "safe_fields_confirmed", "metadata": {"fields": ids}}
                saved = client.patch(check_path, json={"review": check, "expected_revision": check["review_revision"], "events": [bulk]})
                assert saved.status_code == 200, saved.text
                check = client.get(check_path).json()
                assert [row["content"] for row in check["technical_requirements"][:3]] == ["抛丸。", "油漆-清漆。", "电镀-镀彩锌"]
                assert check["technical_requirements"][2]["original_content"] == "表面处理：表面处理 镀锌五彩"
                assert check["technical_requirements"][3]["need_human_review"] is True
                check["technical_requirements"][3]["need_human_review"] = False
                single = {"event_type": "technical_requirement_confirmed", "metadata": {"requirement_id": "conflict"}}
                saved = client.patch(check_path, json={"review": check, "expected_revision": check["review_revision"], "events": [single]})
                assert saved.status_code == 200, saved.text
                check = client.get(check_path).json()
                assert check["technical_requirements"][3]["need_human_review"] is False
                assert len(check["technical_requirements"][3]["surface_mapping"]["verification"]["readings"]) == 2
                assert check["technical_requirements"][3]["surface_mapping"]["catalog_ids"] == []
                reviewed = client.get(check_path + "/generation-package").json()["parameter_package"]
                reviewed_text = reviewed["solidworks_preview"]["technicalRequirements"]["技术要求"]
                for term in ("抛丸", "油漆-清漆", "电镀-镀彩锌", "喷丸"):
                    assert reviewed_text.count("表面处理：" + term) == 1, reviewed_text
                assert "表面处理：表面处理" not in reviewed_text
                check["technical_requirements"][4]["need_human_review"] = False
                single = {"event_type": "technical_requirement_confirmed", "metadata": {"requirement_id": "heading"}}
                rejected = client.patch(check_path, json={"review": check, "expected_revision": check["review_revision"], "events": [single]})
                assert rejected.status_code == 422 and "正文残缺" in rejected.json()["detail"]["message"], rejected.text
                endpoint = "/api/reviews/surface"
                current = client.get(endpoint).json()
                initial = build_generation_parameter_package(current)
                assert not any(v["type"] == "surface" for v in initial["generation_parameters"]["technical_requirements"])
                # A content edit combined with the existing batch-confirm audit
                # may save in one transaction; do not revoke that new decision.
                for item in current["technical_requirements"]:
                    item["need_human_review"] = False
                    if item.get("surface_mapping"):
                        item["content"] = CHINESE + " 保持清洁。"
                        item["surface_mapping"]["selection_mode"] = "manual"
                fields = ["technical_requirements." + v["requirement_id"] for v in current["technical_requirements"]]
                saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"], "events": [{"client_event_id": "surface-bulk", "event_type": "safe_fields_confirmed", "metadata": {"fields": fields}}]})
                assert saved.status_code == 200, saved.text
                current = client.get(endpoint).json()
                assert all(v["need_human_review"] is False for v in current["technical_requirements"])
                package = client.get(endpoint + "/generation-package").json()["parameter_package"]
                text = package["solidworks_preview"]["technicalRequirements"]["技术要求"]
                assert "Fe/Ep" not in text and text.count(CHINESE) == 1, text
                assert next(v for v in package["generation_parameters"]["technical_requirements"] if v.get("surface_mapping"))["surface_mapping"]["catalog_ids"] == [company_id("电镀-镀彩锌")]
                created = client.post(endpoint + "/generation-jobs", json={**create_request("surface-frozen"), "expected_review_revision": current["review_revision"]})
                assert created.status_code == 202, created.text
                job = created.json()["generation_job"]
                frozen = deepcopy(submissions[-1]); assert frozen["models"][0]["technicalRequirements"]["技术要求"] == text
                previous = deepcopy(current)
                first = current["technical_requirements"][0]
                first["surface_mapping"]["catalog_ids"] = [company_id("电镀-镀白锌")]
                first["need_human_review"] = False
                saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"], "events": [{"event_type": "technical_requirement_confirmed", "metadata": {"requirement_id": first["requirement_id"]}}]})
                assert saved.status_code == 200, saved.text
                current = client.get(endpoint).json(); first = current["technical_requirements"][0]
                assert first["need_human_review"] is True and first["surface_mapping"]["conflict"] is True
                assert client.patch(endpoint, json={"review": previous, "expected_revision": previous["review_revision"]}).status_code == 409
                # Explicit none preserves the text and can subsequently confirm.
                first["surface_mapping"].update(catalog_ids=[], selection_mode="none", conflict=False)
                saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"]})
                assert saved.status_code == 200, saved.text
                current = client.get(endpoint).json(); first = current["technical_requirements"][0]
                assert first["surface_mapping"]["selection_mode"] == "none" and first["content"].startswith(CHINESE)
                first["need_human_review"] = False
                saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"], "events": [{"event_type": "technical_requirement_confirmed", "metadata": {"requirement_id": first["requirement_id"]}}]})
                assert saved.status_code == 200, saved.text
                reopened = client.get(endpoint).json()
                assert reopened["technical_requirements"][0]["need_human_review"] is False
                assert reopened["technical_requirements"][0]["surface_mapping"]["catalog_ids"] == []
                # Invalid catalog ID cannot be released to a new SW package.
                first = reopened["technical_requirements"][0]; first["surface_mapping"].update(catalog_ids=["invented"], selection_mode="manual")
                first["need_human_review"] = False
                saved = client.patch(endpoint, json={"review": reopened, "expected_revision": reopened["review_revision"]})
                assert saved.status_code == 200, saved.text
                assert client.get(endpoint).json()["technical_requirements"][0]["need_human_review"] is True
                with repo._session() as session:
                    record = session.get(GenerationJobRecord, job["generation_id"])
                    assert record.execution_options["solidworks_payload"] == frozen
                    assert next(v for v in record.parameter_package["generation_parameters"]["technical_requirements"] if v.get("surface_mapping"))["surface_mapping"]["catalog_ids"] == [company_id("电镀-镀彩锌")]
            repo.dispose()
        print("Company surface API: read-only catalog, legacy protection, batch/single confirmation, CAS, conflict/invalid ID protection, explicit none, reopen and frozen mock SW passed")
    finally:
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness, standard_selector.standard_references, api._post_solidworks_command = original


if __name__ == "__main__": main()
