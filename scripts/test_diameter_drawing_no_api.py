"""Temporary DB, local saved inputs and simulated SW; never touch real orders."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review, create_request
from fastapi.testclient import TestClient
from ai_design_review import standard_selector
from ai_design_review.review_persistence import ReviewPersistence
from ai_design_review.generation_persistence import GenerationStore, GenerationJobRecord
from ai_design_review.diameter_linkage import apply_diameter_linkage, group_state
from ai_design_review.solidworks import build_solidworks_command


def main():
    original = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness, standard_selector.standard_references
    api.verify_review_roughness = lambda *a, **k: None
    standard_selector.standard_references = lambda *a, **k: []
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api.REVIEW_PERSISTENCE = repo = ReviewPersistence(f"sqlite+pysqlite:///{root / 'linkage.db'}")
            repo.create_schema_for_testing(); api.API_RUN_ROOT = root / "runs"; api.API_RUN_ROOT.mkdir()
            review = ready_review(); p = review["spring_parameters"]
            p.update({f: {"value": v, "unit": "mm", "source": ["qwen_vision", "human_confirmed"], "need_human_review": False, "tolerance_upper": .2, "tolerance_lower": -.2} for f, v in (("wire_diameter", 2), ("outer_diameter", 20), ("inner_diameter", 16), ("mean_diameter", 18))})
            review["drawing_summary"]["drawing_no"] = "OLD-001"
            repo.create_review("linkage", review, owner=OWNER)
            with TestClient(api.app) as client:
                endpoint = "/api/reviews/linkage"
                old = client.get(endpoint).json()
                assert "diameter_linkage" not in old
                # Backend independently enforces an ordinary single-field edit.
                changed = deepcopy(old); changed["spring_parameters"]["outer_diameter"]["value"] = 24
                saved = client.patch(endpoint, json={"review": changed, "expected_revision": old["review_revision"], "events": [{"client_event_id": "direct-outer", "event_type": "parameter_value_updated", "target_field": "outer_diameter"}]})
                assert saved.status_code == 200, saved.text
                current = client.get(endpoint).json(); cp = current["spring_parameters"]
                assert [cp[f]["value"] for f in ("outer_diameter", "inner_diameter", "mean_diameter")] == [24, 20, 22]
                assert all(cp[f]["need_human_review"] for f in ("outer_diameter", "inner_diameter", "mean_diameter"))
                assert cp["inner_diameter"]["tolerance_upper"] == .2
                assert current["diameter_linkage"]["original_parameters"]["inner_diameter"]["value"] == 16
                stale = client.patch(endpoint, json={"review": old, "expected_revision": old["review_revision"]})
                assert stale.status_code == 409
                # Confirmation and reopening cannot reactivate legacy completion.
                for f in ("outer_diameter", "inner_diameter", "mean_diameter"):
                    cp[f]["need_human_review"] = False; cp[f]["source"].append("human_confirmed")
                response = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"]})
                assert response.status_code == 200, response.text
                current = client.get(endpoint).json()
                assert current["spring_parameters"]["mean_diameter"]["need_human_review"] is False
                # A real frozen local task keeps its original drawing number.
                created = client.post(endpoint + "/generation-jobs", json={**create_request("diameter-old-drawing"), "expected_review_revision": current["review_revision"]})
                assert created.status_code == 202, created.text
                frozen = created.json()["generation_job"]
                for number in ("  00123  ", " YD-001 23 ", ""):
                    current["drawing_summary"]["drawing_no"] = number
                    saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"]})
                    assert saved.status_code == 200, saved.text
                    current = client.get(endpoint).json()
                    assert current["drawing_summary"]["drawing_no"] == number.strip()
                    package = client.get(endpoint + "/generation-package")
                    assert package.status_code == 200, package.text
                    package = package.json()["parameter_package"]
                    title = build_solidworks_command("1000000001", package, current)["models"][0]["titleBlockProperties"]
                    assert title.get("客户图号") == (number.strip() or None)
                store = GenerationStore(repo)
                with repo._session() as session:
                    existing = session.get(GenerationJobRecord, frozen["generation_id"])
                    assert existing.parameter_package["source"]["drawing_no"] == "OLD-001"
                # Wire edits keep the persisted driver; no independent API needed.
                current["spring_parameters"]["wire_diameter"]["value"] = 3
                saved = client.patch(endpoint, json={"review": current, "expected_revision": current["review_revision"]})
                assert saved.status_code == 200, saved.text
                current = client.get(endpoint).json()
                assert current["spring_parameters"]["outer_diameter"]["value"] == 24
                assert current["spring_parameters"]["inner_diameter"]["value"] == 18
                assert current["spring_parameters"]["mean_diameter"]["value"] == 21
            print("Diameter/drawing number API: atomic recompute, confirmation, CAS, reopening, leading zero, empty value, SW preview and task freezing passed")
    finally:
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness, standard_selector.standard_references = original


if __name__ == "__main__": main()
