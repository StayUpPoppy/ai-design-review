from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "demo-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "demo-user"
os.environ["AI_REVIEW_MOCK_REAL_NAME"] = "Demo User"
os.environ["AI_REVIEW_MOCK_ORG_ID"] = "demo-org"
os.environ["AI_REVIEW_MOCK_ORG_NAME"] = "Demo Org"

from ai_design_review import api  # noqa: E402


def main() -> None:
    with TestClient(api.app) as client:
        review = client.get("/api/samples/mixed-review")
        assert review.status_code == 200, review.text
        assert review.headers["content-type"].startswith("application/json")
        assert review.json()["drawing_summary"]["spring_type"] == "compression_spring"

        preview = client.get("/api/samples/spring-preview")
        assert preview.status_code == 200, preview.text
        assert preview.headers["content-type"].startswith("image/png")
        assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")

    print("demo sample API tests passed")


if __name__ == "__main__":
    main()
