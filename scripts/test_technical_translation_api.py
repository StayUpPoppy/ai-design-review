from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "translation-test-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "translation-test-user"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient
from ai_design_review import api
from ai_design_review.io_utils import write_json
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.technical_translation import TechnicalTranslationEngine
from technical_translation_test_support import protected_reply


def main():
    with tempfile.TemporaryDirectory(prefix="translation-api-") as directory:
        root = Path(directory)
        job = root / "translation-test"
        job.mkdir()
        review = {"drawing_summary": {"spring_type": "compression_spring"}, "spring_parameters": {}, "technical_requirements": [
            {"requirement_id": "stable-id", "type": "process", "content": "Shear modulus G* = 80000 MPa", "need_human_review": False}], "manual_confirmations": {}}
        write_json(job / "review.json", review)
        write_json(job / "owner.json", {"user_id": "translation-test-user", "username": "translation-test-user"})
        original = (job / "review.json").read_bytes()
        engine = TechnicalTranslationEngine(completion_fn=lambda rows: {"requirements": [{"requirement_id": row["requirement_id"], "content": protected_reply(row, "剪切模量 G* = 80000 MPa"), "source_language": "en"} for row in rows]})
        path = "/api/reviews/translation-test/technical-requirements/translate"
        body = {"requirements": [{"requirement_id": "stable-id", "source_snapshot": {"content": review["technical_requirements"][0]["content"], "type": "process"}}]}
        with patch.object(api, "API_RUN_ROOT", root), patch.object(api, "REVIEW_PERSISTENCE", ReviewPersistence(database_url="")), patch.object(api, "TechnicalTranslationEngine", lambda: engine):
            client = TestClient(api.app)
            response = client.post(path, json=body)
            assert response.status_code == 200, response.text
            result = response.json()["requirements"][0]
            assert result["translation_status"] == "translated" and result["source_snapshot"] == body["requirements"][0]["source_snapshot"]
            assert (job / "review.json").read_bytes() == original, "Translation endpoint must not save or confirm"
            chinese = "7.未注尺寸以3D为准"
            historical = {"requirement_id": "historical-3d", "type": "other", "content": chinese, "original_content": chinese,
                          "source_language": "zh", "translation_status": "failed", "translation_error": "译文仍包含外语说明，请重试或人工填写中文。",
                          "translation_input_snapshot": {"content": chinese, "type": "other"}, "translation_source": "qwen_text:old", "need_human_review": True}
            unsafe = {**historical, "requirement_id": "unsafe", "translation_error": "翻译改变了数值或公差，原文已保留，请核对后重试。"}
            review["technical_requirements"].extend([historical, unsafe])
            write_json(job / "review.json", review)
            historical_original = (job / "review.json").read_bytes()
            local_engine = TechnicalTranslationEngine()
            recovery_body = {"requirements": [{"requirement_id": item["requirement_id"], "source_snapshot": item["translation_input_snapshot"]} for item in (historical, unsafe)]}
            with patch.object(api, "TechnicalTranslationEngine", lambda: local_engine), patch.object(local_engine, "_complete") as complete:
                recovered = client.post(path, json=recovery_body)
                assert recovered.status_code == 200, recovered.text
                rows = recovered.json()["requirements"]
                assert rows[0]["translation_status"] == "not_required" and rows[0]["content"] == chinese and rows[0]["source_language"] == "zh"
                assert rows[1]["translation_status"] == "failed", "numerical validation failures must not be recovered"
                complete.assert_not_called()
                assert (job / "review.json").read_bytes() == historical_original, "recovery endpoint must remain calculate-only"
                wrong_type = {"requirements": [{"requirement_id": "historical-3d", "source_snapshot": {"content": chinese, "type": "process"}}]}
                assert client.post(path, json=wrong_type).status_code == 409
            original = historical_original
            changed = {"requirements": [{"requirement_id": "stable-id", "source_snapshot": {"content": "older text", "type": "process"}}]}
            assert client.post(path, json=changed).status_code == 409
            assert client.post(path, json={"requirements": body["requirements"] * 2}).status_code == 400
            assert client.post(path, json={"requirements": []}).status_code == 400
            write_json(job / "owner.json", {"user_id": "another-user", "username": "another-user"})
            assert client.post(path, json=body).status_code in {403, 404}
            assert (job / "review.json").read_bytes() == original
        # Initial recognition translations are audit events in the same create
        # transaction, without an extra revision or new table.
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'audit.db'}")
        repository.create_schema_for_testing()
        try:
            review["change_history"] = [{"client_event_id": "translation-initial", "event_type": "technical_requirement_translated", "source": "machine_translation", "target_field": "technical_requirements.stable-id", "metadata": {"requirement_id": "stable-id"}}]
            created = repository.create_review("audit-test", review, owner={"user_id": "translation-test-user"})
            assert created["revision"] == 1 and len(created["events"]) == 2
            assert any(event["event_type"] == "technical_requirement_translated" for event in repository.list_change_events("audit-test", owner_user_id="translation-test-user"))
        finally:
            repository.dispose()
    print("PASS: translate API ownership, source conflict, ID checks and calculate-only behavior")


if __name__ == "__main__":
    main()
