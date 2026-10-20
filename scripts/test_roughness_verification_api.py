"""Temporary SQLite/PDF only: legacy draft upgrades and revision/save protection."""
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "roughness-test"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "roughness-test"
os.environ["AI_REVIEW_ALLOW_SQLITE_GENERATION_TESTS"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.io_utils import write_json
from ai_design_review.generation_readiness import build_generation_parameter_package
from test_solidworks_export import base_review

FIELD = "surface_roughness_ra"
OWNER = {"user_id": "roughness-test", "username": "roughness-test"}


def fixture(root, repo, job, *, real=False, protection=None):
    import fitz
    folder = root / job
    (folder / "inputs").mkdir(parents=True); (folder / "pages").mkdir()
    doc = fitz.open(); page = doc.new_page(width=400, height=300)
    page.insert_text((40, 80), "Ra3.2" if real else "DATUM PLANE")
    doc.save(folder / "inputs/drawing.pdf"); page.get_pixmap().save(folder / "pages/page-1.png"); doc.close()
    review = base_review()
    review["spring_parameters"][FIELD] = {
        "value": 3.2, "unit": "μm", "source": ["qwen_vision"], "need_human_review": True,
        "evidence": "▲：加工基准面 (Ra3.2)", "page": 1, "position": None,
        "roughness_candidates": [{"value": 3.2, "unit": "μm", "source": "qwen_vision", "page": 1, "evidence": "▲：加工基准面 (Ra3.2)", "evidence_status": "direct", "location": "两端面"}]}
    review["spring_parameters"][FIELD].update(protection or {})
    write_json(folder / "review.json", review); write_json(folder / "owner.json", OWNER)
    write_json(folder / "candidates.json", {"candidates": [], "raw_payloads": {}})
    repo.create_review(job, review, artifact_dir=str(folder), owner=OWNER)
    return review


def run():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        repo = ReviewPersistence(f"sqlite+pysqlite:///{root / 'test.db'}"); repo.create_schema_for_testing()
        with patch.object(api, "REVIEW_PERSISTENCE", repo), patch.object(api, "API_RUN_ROOT", root / "runs"), \
             patch("ai_design_review.engines.ocr_providers.RapidOcrProvider.recognize", return_value=[]) as ocr, TestClient(api.app) as client:
            fixture(api.API_RUN_ROOT, repo, "legacy")
            first = client.get("/api/reviews/legacy"); assert first.status_code == 200, first.text
            draft = first.json(); item = draft["spring_parameters"][FIELD]
            assert item["value"] is None and item["need_human_review"]
            assert item["roughness_original_recognition"]["value"] == 3.2
            assert item["roughness_verification_adjustment"]["before"]["value"] == 3.2
            stored = repo.get_review("legacy", owner_user_id="roughness-test")
            assert stored["revision"] == 1 and stored["review"]["spring_parameters"][FIELD]["value"] == 3.2, "GET only upgrades a draft"
            called = ocr.call_count
            assert client.get("/api/reviews/legacy").json() == draft
            assert ocr.call_count == called
            saved = client.patch("/api/reviews/legacy", json={"review": draft, "expected_revision": 1, "events": []})
            assert saved.status_code == 200, saved.text
            reopened = client.get("/api/reviews/legacy").json()
            assert reopened["spring_parameters"][FIELD]["value"] is None
            history = repo.list_change_events("legacy", owner_user_id="roughness-test")
            assert any(e["event_type"] == "roughness_evidence_verified" for e in history)
            manual = deepcopy(reopened)
            manual["spring_parameters"][FIELD].update(value=6.3, source=["human_edited", "human_confirmed"], need_human_review=False)
            saved = client.patch("/api/reviews/legacy", json={"review": manual, "expected_revision": 2, "events": []})
            assert saved.status_code == 200, saved.text
            assert client.patch("/api/reviews/legacy", json={"review": draft, "expected_revision": 1, "events": []}).status_code == 409
            final = client.get("/api/reviews/legacy").json()
            assert final["spring_parameters"][FIELD]["value"] == 6.3
            assert build_generation_parameter_package(final)["solidworks_preview"]["titleBlockProperties"]["表面粗糙度"] == 6.3
            for n, protection in enumerate(({"source": ["human_roughness_reference"]}, {"source": ["human_confirmed"], "need_human_review": False}, {"need_human_review": False}, {"need_human_review": None})):
                fixture(api.API_RUN_ROOT, repo, f"protected-{n}", protection=protection)
                read = client.get(f"/api/reviews/protected-{n}").json()["spring_parameters"][FIELD]
                assert read["value"] == 3.2
            fixture(api.API_RUN_ROOT, repo, "real", real=True)
            read = client.get("/api/reviews/real").json()["spring_parameters"][FIELD]
            assert read["value"] == 3.2 and read["need_human_review"]
            assert read["roughness_candidates"][0]["independent_evidence"][0]["source"] == "pdf_text"
            # Upgrade an existing v3 document without moving unrelated fields.
            from ai_design_review.drawing_annotations import build_annotations
            folder = api.API_RUN_ROOT / "real"
            full = client.get("/api/reviews/real").json()
            document = build_annotations(full, folder, lambda p: f"/api/reviews/real/artifacts/{p.as_posix()}", allow_ocr=False)
            document.pop("roughness_evidence_signature", None)
            for a in document["annotations"]:
                if a["field"] == FIELD:
                    a["locations"] = []
                if a["field"] == "wire_diameter":
                    a["locations"] = [{"location_id": "wire-manual", "page": 1, "source": "manual", "bbox": {"x": .1, "y": .1, "width": .02, "height": .02}, "anchor": {"x": .11, "y": .11}, "bubble": {"x": .2, "y": .2}}]
            repo.save_drawing_annotations("real", owner_user_id=OWNER["user_id"], initial=document)
            upgraded = client.get("/api/reviews/real/annotations").json()
            assert upgraded["annotation_revision"] == 2
            assert next(a for a in upgraded["annotations"] if a["field"] == FIELD)["locations"][0]["evidence_value"] == 3.2
            for old, new in zip(document["annotations"], upgraded["annotations"]):
                if old["field"] != FIELD:
                    assert old == new
            assert client.get("/api/reviews/real/annotations").json() == upgraded
            full["spring_parameters"]["free_length"]["value"] = 85
            assert client.patch("/api/reviews/real", json={"review": full, "expected_revision": 1, "events": []}).status_code == 200
            assert client.get("/api/reviews/real/annotations").json()["annotation_revision"] == 2
            retried = client.post("/api/reviews/real/annotations/relocalize", json={"source_document_id": upgraded["source_document_id"], "expected_annotation_revision": 2})
            assert retried.status_code == 200, retried.text
            assert retried.json()["roughness_update"]["parameter"]["value"] == 3.2
            assert retried.json()["roughness_update"]["based_on_revision"] == 2
            assert client.post("/api/reviews/real/annotations/relocalize", json={"source_document_id": upgraded["source_document_id"], "expected_annotation_revision": 2}).status_code == 409
            # Two ordinary OCR/PDF numbers can verify the scalar without
            # assigning either glyph to an end in a drawing with no view.
            import fitz
            pending = fixture(api.API_RUN_ROOT, repo, "numeric-only")
            folder = api.API_RUN_ROOT / "numeric-only"
            pdf = fitz.open(); page = pdf.new_page(width=400, height=300)
            page.insert_text((40, 80), "6.3"); page.insert_text((230, 180), "6.3")
            (folder / "inputs/drawing.pdf").write_bytes(pdf.tobytes())
            page.get_pixmap().save(folder / "pages/page-1.png"); pdf.close()
            pending["spring_parameters"][FIELD].update(value=6.3, evidence="两端面Ra6.3", roughness_candidates=[{
                "value": 6.3, "unit": "μm", "source": "qwen_vision", "roughness_model_claim": True, "page": 1,
                "position": None, "surface_location": "两端面", "evidence": "两端面Ra6.3"}])
            repo.save_review("numeric-only", pending, expected_revision=1, owner=OWNER)
            draft = client.get("/api/reviews/numeric-only").json()
            value = draft["spring_parameters"][FIELD]
            assert value["value"] == 6.3 and value["value_verified"] and value["recognition_state"] == "needs_location"
            annotations = client.get("/api/reviews/numeric-only/annotations").json()
            ra = next(a for a in annotations["annotations"] if a["field"] == FIELD)
            assert ra["original_value"] == 6.3 and not ra["locations"]
            assert "表面粗糙度" not in build_generation_parameter_package(draft)["solidworks_preview"]["titleBlockProperties"]
            value.update(need_human_review=False, source=["human_confirmed"])
            assert client.patch("/api/reviews/numeric-only", json={"review": draft, "expected_revision": 2, "events": []}).status_code == 200
            reopened = client.get("/api/reviews/numeric-only").json()
            assert reopened["spring_parameters"][FIELD]["recognition_state"] == "needs_location"
            assert build_generation_parameter_package(reopened)["solidworks_preview"]["titleBlockProperties"]["表面粗糙度"] == 6.3
            assert client.get("/api/reviews/not-owned").status_code == 404
    print("PASS: roughness legacy GET drafts, revisioned saving/audit, manual race protection, PDF proof and SW parity")


if __name__ == "__main__":
    run()
