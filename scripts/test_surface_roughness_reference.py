"""Optional Ra metadata persists without becoming a default or changing frozen tasks."""
from __future__ import annotations
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.generation_readiness import build_generation_parameter_package, assess_generation_readiness
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.surface_roughness import ensure_surface_roughness_parameter
from ai_design_review.review_persistence import ReviewPersistence
from test_solidworks_export import base_review


def cases():
    rows = []
    for closed, ground in ((1, 1), (1, 0), (0, 1), (0, 0), (None, None)):
        for stage in ("missing", "pending", "confirmed", "pending_6_3", "confirmed_6_3", "dismissed", "custom", "cleared"):
            review = base_review()
            parameters = review["spring_parameters"]
            parameters["end_coils_closed"] = {"value": closed, "need_human_review": closed is None}
            parameters["end_grinding"] = {"value": ground, "need_human_review": ground is None}
            value = 12.5 if stage in {"pending", "confirmed"} else 6.3 if stage in {"custom", "pending_6_3", "confirmed_6_3"} else None
            roughness = {"value": value, "unit": "μm", "surface_location": "两端面", "evidence": "", "position": None,
                         "source": [] if stage == "missing" else ["human_edited"],
                         "need_human_review": stage not in {"confirmed", "confirmed_6_3", "custom"}}
            if stage in {"pending", "confirmed", "pending_6_3", "confirmed_6_3"}:
                roughness["source"].append("human_roughness_reference")
            if stage != "missing":
                roughness["roughness_reference_dismissed"] = stage in {"dismissed", "cleared"}
            parameters["surface_roughness_ra"] = roughness
            before = deepcopy(roughness)
            package = build_generation_parameter_package(review)
            preview = package["solidworks_preview"]
            if stage in {"confirmed", "confirmed_6_3", "custom"}:
                assert preview["titleBlockProperties"]["表面粗糙度"] == value
            else:
                assert "表面粗糙度" not in preview["titleBlockProperties"]
            assert "粗糙度" not in preview["extraProperties"]["技术要求"]
            assert "roughness_reference_dismissed" not in json.dumps(preview)
            assert review["spring_parameters"]["surface_roughness_ra"] == before
            assert not any(item["field"] == "surface_roughness_ra" for item in assess_generation_readiness(review)["pending_fields"])
            frozen = deepcopy(package)
            command = build_solidworks_command("1000000199", package, review)
            review["spring_parameters"]["surface_roughness_ra"]["value"] = 3.2
            assert build_solidworks_command("1000000199", package, review) == command and package == frozen
            review["spring_parameters"]["surface_roughness_ra"] = before
            rows.append({"name": f"{closed}-{ground}-{stage}", "review": review, "package": package})
    # Declining/clearing is a human decision, so old matching notes cannot refill the parameter.
    cleared = deepcopy(rows[-1]["review"])
    cleared["technical_requirements"].append({"type": "surface_roughness", "content": "两端面粗糙度 Ra 12.5μm", "need_human_review": False})
    ensure_surface_roughness_parameter(cleared)
    assert cleared["spring_parameters"]["surface_roughness_ra"]["value"] is None
    return rows


def run():
    rows = cases()
    with tempfile.TemporaryDirectory(prefix="roughness-reference-") as directory:
        repository = ReviewPersistence(f"sqlite+pysqlite:///{Path(directory) / 'review.db'}")
        repository.create_schema_for_testing()
        owner = {"user_id": "roughness-reference", "username": "test"}
        try:
            for row in rows:
                identity = row["name"]
                repository.create_review(identity, row["review"], owner=owner)
                reopened = repository.get_review(identity, owner_user_id=owner["user_id"])["review"]
                assert reopened["spring_parameters"]["surface_roughness_ra"] == row["review"]["spring_parameters"]["surface_roughness_ra"]
                assert build_generation_parameter_package(reopened)["solidworks_preview"] == row["package"]["solidworks_preview"]
        finally:
            repository.dispose()
    return rows


if __name__ == "__main__":
    rows = run()
    print(json.dumps(rows, ensure_ascii=True) if "--json" in sys.argv else f"PASS: {len(rows)} Ra reference/confirmation/end-state cases, persistence and frozen requests")
