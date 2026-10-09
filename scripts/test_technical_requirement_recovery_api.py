from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "recovery-test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.io_utils import write_json
from ai_design_review.review_persistence import ReviewPersistence


def main():
    with tempfile.TemporaryDirectory(prefix="note-recovery-") as directory:
        root = Path(directory)
        job = root / "test"
        job.mkdir()
        review = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {}, "technical_requirements": [], "manual_confirmations": {}}
        write_json(job / "review.json", review)
        write_json(job / "owner.json", {"user_id": "recovery-test"})
        write_json(job / "qwen_vision_raw.json", {"parsed": {"spring_type": "compression_spring", "technical_requirements": [
            {"type": "process", "content": "施加力 F3 并保持负载不少于 6 小时", "original_number": "9"},
            {"type": "process", "content": "强压后检查残余变形", "original_number": "10"}]}})
        write_json(job / "candidates.json", {"candidates": [{"field": "other_requirement", "value": "备用记录", "source": "ocr"}]})
        before = {path.name: path.read_bytes() for path in job.iterdir()}
        path = "/api/reviews/test/technical-requirements/recover-preview"
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")), patch.object(api.QwenVisionEngine, "extract_with_raw", side_effect=AssertionError("must not call recognition")):
            client = TestClient(api.app)
            result = client.post(path, json={"expected_revision": None})
            assert result.status_code == 200, result.text
            data = result.json()
            assert data["source"] == "qwen_vision_raw" and len(data["items"]) == 2
            assert data["items"][0]["requirement"]["need_human_review"] is True
            assert client.post(path, json={"expected_revision": 9}).status_code == 409
            assert before == {file.name: file.read_bytes() for file in job.iterdir()}, "preview must not mutate any stored artifact"
            write_json(job / "qwen_vision_raw.json", {"parsed": {"parameters": "corrupt saved record"}})
            assert client.post(path, json={}).json()["source"] == "candidates"
            write_json(job / "qwen_vision_raw.json", {"parsed": {"technical_requirements": []}})
            assert client.post(path, json={}).json()["source"] == "candidates"
            write_json(job / "candidates.json", {"candidates": []})
            assert client.post(path, json={}).json()["source"] == "none"
            write_json(job / "owner.json", {"user_id": "another-user"})
            assert client.post(path, json={}).status_code in {403, 404}
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'reviews.db'}")
        repository.create_schema_for_testing()
        try:
            repository.create_review("db-test", review, owner={"user_id": "recovery-test"})
            db_job = root / "db-test"
            db_job.mkdir()
            write_json(db_job / "candidates.json", {"candidates": [{"field": "process_requirement", "value": "检查残余变形", "source": "ocr"}]})
            with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", repository):
                client = TestClient(api.app)
                db_path = "/api/reviews/db-test/technical-requirements/recover-preview"
                assert client.post(db_path, json={"expected_revision": 1}).status_code == 200
                assert client.post(db_path, json={"expected_revision": 0}).status_code == 409
                stored = repository.get_review("db-test", owner_user_id="recovery-test")
                assert stored["revision"] == 1 and stored["review"]["technical_requirements"] == []
                assert len(repository.list_change_events("db-test", owner_user_id="recovery-test")) == 1, "preview must not write audit events"
        finally:
            repository.dispose()
    print("PASS: recovery API ownership, revision, calculate-only behavior, raw priority and fallback")


if __name__ == "__main__":
    main()
