from __future__ import annotations

import copy
import os
import sys
import tempfile
from pathlib import Path

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "annotation-test-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "annotation-test-user"
os.environ["AI_REVIEW_ALLOW_SQLITE_GENERATION_TESTS"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient
from ai_design_review import api  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402
from ai_design_review.generation_readiness import build_generation_parameter_package  # noqa: E402
from ai_design_review.solidworks import build_solidworks_command  # noqa: E402


def fixture(root: Path, repository: ReviewPersistence, job_id="annotations-demo"):
    import fitz

    job_dir = root / job_id
    (job_dir / "inputs").mkdir(parents=True)
    (job_dir / "pages").mkdir()
    doc = fitz.open()
    page = doc.new_page(width=600, height=430)
    page.insert_text((30, 35), "DEMONSTRATION DATA / compression spring")
    texts = [("wire_diameter", 2, "wire diameter 2", 65, 145),
             ("outer_diameter", 28, "outer diameter 28", 400, 180),
             ("free_length", 80, "free length 80", 230, 95),
             ("total_coils", 9, "total coils 9", 70, 310),
             ("active_coils", 7, "active coils 7", 300, 310),
             ("surface_roughness_ra", 12.5, "Ra 12.5", 400, 265)]
    params = {}
    candidates = []
    for field, value, text, x, y in texts:
        page.insert_text((x, y), text)
        params[field] = {"value": value, "unit": "mm", "source": ["qwen_vision", "human_confirmed"], "evidence": text, "need_human_review": False, "human_confirmed": True}
        candidates.append({"field": field, "value": value, "source": "qwen_vision", "confidence": .9, "evidence": text})
    for index in range(9):
        x = 90 + index * 32
        page.draw_line((x, 245), (x + 15, 140), color=(.15, .15, .15), width=1.5)
        page.draw_line((x + 15, 140), (x + 32, 245), color=(.15, .15, .15), width=1.5)
    page.draw_line((80, 115), (390, 115))
    page.draw_line((420, 140), (420, 245))
    preview = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    preview.save(job_dir / "pages" / "page-1.png")
    second = doc.new_page(width=600, height=430)
    second.insert_text((40, 50), "DEMONSTRATION DATA / material SUS304")
    second.insert_text((40, 95), "standard GB/T 1239.2-2009")
    second.get_pixmap(matrix=fitz.Matrix(2, 2)).save(job_dir / "pages" / "page-2.png")
    doc.save(job_dir / "inputs" / "spring.pdf")
    doc.close()
    params.update({"material": {"value": "SUS304", "source": ["qwen_vision"], "evidence": "material SUS304", "need_human_review": True},
                   "standard_no": {"value": "GB/T 1239.2-2009", "source": ["qwen_vision"], "evidence": "standard GB/T 1239.2-2009", "need_human_review": True},
                   "mean_diameter": {"value": 26, "source": ["formula_calculation", "human_confirmed"], "need_human_review": False, "human_confirmed": True},
                   "handedness": {"value": "right", "source": ["human_confirmed"], "human_confirmed": True, "need_human_review": False},
                   "end_type": {"value": "两端并紧", "source": ["human_confirmed"], "human_confirmed": True, "need_human_review": False},
                   "end_grinding": {"value": "两端磨削", "source": ["human_confirmed"], "human_confirmed": True, "need_human_review": False},
                   "accuracy_grade": {"value": "2级", "source": ["company_default"], "default_source": "company_default", "need_human_review": True}})
    review = {"drawing_summary": {"drawing_name": "气泡标注演示（测试数据）", "drawing_no": "DEMO-ANNOTATIONS", "spring_type": "compression_spring", "spring_type_label": "压缩弹簧"},
              "spring_parameters": params, "spring_features": {}, "technical_requirements": [], "standardization_results": [], "change_history": [], "balloons": []}
    owner = {"user_id": "annotation-test-user", "username": "annotation-test-user"}
    write_json(job_dir / "review.json", review)
    write_json(job_dir / "owner.json", owner)
    write_json(job_dir / "candidates.json", {"candidates": candidates, "raw_payloads": {}})
    if repository.configured:
        repository.create_review(job_id, review, artifact_dir=str(job_dir), owner=owner)
    return review


def check(client, repository, job_id):
    path = f"/api/reviews/{job_id}/annotations"
    response = client.get(path)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["annotation_revision"] == 1
    assert len(document["pages"]) == 2
    annotation = next(a for a in document["annotations"] if a["field"] == "wire_diameter")
    assert annotation["locations"], annotation
    old_review = client.get(f"/api/reviews/{job_id}").json()
    original_params = copy.deepcopy(old_review["spring_parameters"])
    before = build_solidworks_command("1000000100", build_generation_parameter_package(copy.deepcopy(old_review)), old_review)
    change = {"annotation_id": "wire_diameter", "location_id": annotation["locations"][0]["location_id"], "page": 1, "anchor": {"x": .15, "y": .25}, "bubble": {"x": .2, "y": .25}}
    body = {"source_document_id": document["source_document_id"], "expected_annotation_revision": 1, "changes": [change]}
    saved = client.patch(path, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["annotation_revision"] == 2
    assert client.get(path).json() == saved.json()
    assert client.patch(path, json=body).status_code == 409
    body["expected_annotation_revision"] = 2
    body["changes"][0]["value"] = 999
    assert client.patch(path, json=body).status_code == 400
    del body["changes"][0]["value"]
    body["changes"][0]["page"] = 9
    assert client.patch(path, json=body).status_code == 400
    after_review = client.get(f"/api/reviews/{job_id}").json()
    assert after_review["spring_parameters"] == original_params
    assert after_review.get("review_revision") == old_review.get("review_revision")
    assert after_review["parameter_reasonableness"] == old_review["parameter_reasonableness"]
    after = build_solidworks_command("1000000100", build_generation_parameter_package(copy.deepcopy(after_review)), after_review)
    assert before == after
    stale = copy.deepcopy(old_review)
    stale["spring_parameters"]["free_length"]["value"] = 85
    response = client.patch(f"/api/reviews/{job_id}", json={"review": stale, "expected_revision": old_review.get("review_revision"), "events": []})
    assert response.status_code == 200, response.text
    assert client.get(path).json()["annotation_revision"] == 2
    assert client.get(f"/api/reviews/{job_id}").json()["spring_parameters"]["free_length"]["value"] == 85
    if repository.configured:
        assert repository.get_review(job_id, owner_user_id="annotation-test-user")["revision"] == 2
        repository.create_review("someone-else", stale, owner={"user_id": "other-user"})
        assert client.get("/api/reviews/someone-else/annotations").status_code == 404
        assert client.patch("/api/reviews/someone-else/annotations", json=body).status_code == 404


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        old_repository, old_root = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'reviews.db'}")
        repository.create_schema_for_testing()
        try:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = repository, root / "api_runs"
            fixture(api.API_RUN_ROOT, repository)
            if "--preview" in sys.argv:
                import uvicorn
                from fastapi.staticfiles import StaticFiles
                api.app.mount("/frontend", StaticFiles(directory=str(Path(__file__).resolve().parents[1] / "frontend"), html=True))
                print("Temporary demo only: http://127.0.0.1:8998/frontend/", flush=True)
                uvicorn.run(api.app, host="127.0.0.1", port=8998)
                return
            with TestClient(api.app) as client:
                check(client, repository, "annotations-demo")
            repository.dispose()
            repository = ReviewPersistence("")
            api.REVIEW_PERSISTENCE = repository
            fixture(api.API_RUN_ROOT, repository, "local-annotations")
            with TestClient(api.app) as client:
                check(client, repository, "local-annotations")
            print("drawing annotation API tests passed: permissions, independent revisions, SW isolation, JSON fallback")
        finally:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = old_repository, old_root
            repository.dispose()


if __name__ == "__main__":
    main()
