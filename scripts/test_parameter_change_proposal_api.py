from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "proposal-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "proposal-user"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "proposal-org"

from ai_design_review import api  # noqa: E402
from ai_design_review.io_utils import write_json  # noqa: E402
from ai_design_review.review_persistence import ReviewPersistence  # noqa: E402


OWNER = {
    "user_id": "proposal-user",
    "username": "proposal-user",
    "real_name": "Proposal User",
    "org_id": "proposal-org",
    "org_name": "Proposal Org",
}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = ReviewPersistence(f"sqlite+pysqlite:///{root / 'proposal.db'}")
        repository.create_schema_for_testing()
        original_repository = api.REVIEW_PERSISTENCE
        original_root = api.API_RUN_ROOT
        try:
            api.REVIEW_PERSISTENCE = repository
            api.API_RUN_ROOT = root / "api_runs"
            job_dir = api.API_RUN_ROOT / "proposal-review"
            job_dir.mkdir(parents=True)
            review = _review()
            write_json(job_dir / "review.json", review)
            repository.create_review("proposal-review", review, artifact_dir=str(job_dir), owner=OWNER)

            with TestClient(api.app) as client:
                chat = client.post(
                    "/api/reviews/proposal-review/standardization-chat",
                    json={
                        "message": "中径改成26mm",
                        "use_llm": False,
                        "expected_revision": 1,
                    },
                )
                assert chat.status_code == 200, chat.text
                chat_payload = chat.json()
                proposal = chat_payload["change_proposal"]
                assert proposal["status"] in {"ready", "warning"}
                assert chat_payload["review_revision"] == 2

                apply = client.post(
                    f"/api/reviews/proposal-review/parameter-change-proposals/{proposal['proposal_id']}/apply",
                    json={"version": proposal["version"], "expected_review_revision": 2},
                )
                assert apply.status_code == 200, apply.text
                applied = apply.json()
                assert applied["review_revision"] == 3
                assert applied["change_proposal"]["status"] == "applied"
                parameters = applied["review"]["spring_parameters"]
                assert parameters["mean_diameter"]["value"] == 26
                assert parameters["outer_diameter"]["value"] == 32
                assert parameters["inner_diameter"]["value"] == 20

                duplicate = client.post(
                    f"/api/reviews/proposal-review/parameter-change-proposals/{proposal['proposal_id']}/apply",
                    json={"version": proposal["version"], "expected_review_revision": 3},
                )
                assert duplicate.status_code == 409
                assert duplicate.json()["detail"]["code"] == "proposal_not_applyable"

                second_chat = client.post(
                    "/api/reviews/proposal-review/standardization-chat",
                    json={"message": "自由长度改成65mm", "use_llm": False, "expected_revision": 3},
                )
                assert second_chat.status_code == 200, second_chat.text
                second = second_chat.json()["change_proposal"]
                assert second_chat.json()["review_revision"] == 4
                discard = client.post(
                    f"/api/reviews/proposal-review/parameter-change-proposals/{second['proposal_id']}/discard",
                    json={"version": second["version"], "expected_review_revision": 4},
                )
                assert discard.status_code == 200, discard.text
                assert discard.json()["change_proposal"]["status"] == "discarded"
                assert discard.json()["review"]["spring_parameters"]["free_length"]["value"] == 70

                technical_chat = client.post(
                    "/api/reviews/proposal-review/standardization-chat",
                    json={"message": "新增一条技术要求：表面镀锌。", "use_llm": False, "expected_revision": 5},
                )
                assert technical_chat.status_code == 200, technical_chat.text
                technical_proposal = technical_chat.json()["change_proposal"]
                assert technical_proposal["technical_requirement_changes"][0]["operation"] == "add"
                assert technical_chat.json()["review_revision"] == 6

                technical_apply = client.post(
                    f"/api/reviews/proposal-review/parameter-change-proposals/{technical_proposal['proposal_id']}/apply",
                    json={"version": technical_proposal["version"], "expected_review_revision": 6},
                )
                assert technical_apply.status_code == 200, technical_apply.text
                technical_payload = technical_apply.json()
                assert technical_payload["review_revision"] == 7
                requirement = technical_payload["review"]["technical_requirements"][0]
                assert requirement["content"] == "表面镀锌"
                assert requirement["need_human_review"] is False
                assert requirement["requirement_id"].startswith("techreq_")
        finally:
            api.REVIEW_PERSISTENCE = original_repository
            api.API_RUN_ROOT = original_root
            repository.dispose()

    print("parameter change proposal API tests passed")


def _review() -> dict:
    return {
        "drawing_summary": {"spring_type": "compression_spring"},
        "spring_parameters": {
            "wire_diameter": _param(6, "mm"),
            "mean_diameter": _param(42, "mm"),
            "outer_diameter": _param(48, "mm"),
            "inner_diameter": _param(36, "mm"),
            "free_length": _param(70, "mm"),
            "total_coils": _param(10, "turns"),
            "active_coils": _param(8, "turns"),
            "handedness": _param("right"),
            "end_grinding": _param(1),
            "end_coils_closed": _param(1),
            "load_points": [],
        },
        "technical_requirements": [],
        "standard_selection": {},
        "standardization_results": [],
        "derived_parameters": {},
        "manual_confirmations": {},
    }


def _param(value: object, unit: str | None = None) -> dict:
    return {"value": value, "unit": unit, "need_human_review": False, "source": ["human_confirmed"]}


if __name__ == "__main__":
    main()
