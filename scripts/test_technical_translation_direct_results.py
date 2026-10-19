"""Shared direct-output policy: protocol errors only, pending confirmation and frozen SW."""
from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).parent)]
from ai_design_review.technical_translation import (
    TechnicalTranslationEngine, apply_translation_result, prepare_review_translations,
    translation_blocks_export, translation_snapshot,
)
from ai_design_review.technical_translation_recovery import revalidate_translations
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command
from ai_design_review.review_persistence import ReviewPersistence, RevisionConflictError
from test_generation_readiness import _ready_review


def run():
    fixtures = json.loads((Path(__file__).parent / "fixtures/technical_translation_direct_results.json").read_text(encoding="utf-8"))
    review = _ready_review()
    notes = [{**row, "content": row["original_content"], "need_human_review": False} for row in fixtures]
    review["technical_requirements"] = notes
    calls = []
    def complete(rows):
        calls.append(rows)
        return {"requirements": [{"requirement_id": row["requirement_id"], "content": row["content"], "source_language": "de"} for row in fixtures]}
    engine = TechnicalTranslationEngine(completion_fn=complete)
    for item, result in zip(notes, engine.translate(notes)):
        assert result["translation_status"] == "translated" and not result["translation_warnings"]
        assert apply_translation_result(review, item, result)
        assert item["need_human_review"] and item["human_confirmed"] is False
        assert not translation_blocks_export(item)
        assert item["translation_output_snapshot"] == translation_snapshot(item)
    assert not build_generation_parameter_package(review)["generation_parameters"]["technical_requirements_text"]
    with patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("No repeat model call")):
        assert len(prepare_review_translations(review)) == len(fixtures)
        for item in notes:
            legacy = deepcopy(item); legacy.pop("translation_output_snapshot")
            assert not translation_blocks_export(legacy)
            assert TechnicalTranslationEngine().translate([legacy])[0]["translation_status"] == "translated"
    for note in notes:
        note["need_human_review"] = False
    with patch.object(TechnicalTranslationEngine, "_complete", side_effect=AssertionError("No repeat model call")):
        prepare_review_translations(review)
    assert all(note["need_human_review"] is False for note in notes), "Reusing accepted translations must preserve existing confirmations"
    package = build_generation_parameter_package(review)
    command = build_solidworks_command("1000000088", package, review)
    text = command["models"][0]["extraProperties"]["技术要求"]
    for fragment in ["Cu/Ni15/Ag3", "Ls=3.59", "Di", "FN 942010", "LABS", "Hub", "F2=17 mm", "Spring must pass"]:
        assert fragment in text, (fragment, text)
    assert text == package["solidworks_preview"]["extraProperties"]["技术要求"]
    frozen = deepcopy(package)
    notes[0]["content"] = "later edit"
    assert build_solidworks_command("1000000088", frozen, review) == command

    for row in fixtures:
        failed = {**row, "content": row["original_content"], "translation_status": "failed",
                  "translation_error": "历史内容校验失败", "need_human_review": True,
                  "translation_error_details": {"candidate_content": row["content"]}}
        failed["translation_input_snapshot"] = translation_snapshot(failed)
        result = revalidate_translations({}, [failed], [])[0]
        assert result["recovery_mode"] == "automatic" and result["content"] == row["content"]
        assert result["translation_output_snapshot"] == {"content": row["content"], "type": row["type"]}
        edited = {**failed, "source": ["human_edited"]}
        assert revalidate_translations({}, [edited], [])[0]["recovery_mode"] == "preview"
        missing = deepcopy(failed); missing["translation_error_details"] = {}
        assert revalidate_translations({}, [missing], [])[0]["recovery_mode"] == "unavailable"
        # A raw extraction equal to its original is not a saved translation response.
        assert revalidate_translations({}, [missing], [{**row, "content": row["original_content"]}])[0]["recovery_mode"] == "unavailable"
    with tempfile.TemporaryDirectory(prefix="direct-translation-save-") as directory:
        repository = ReviewPersistence(f"sqlite+pysqlite:///{Path(directory) / 'review.db'}")
        repository.create_schema_for_testing()
        owner = {"user_id": "direct-translation-user"}
        try:
            repository.create_review("order", review, owner=owner)
            saved_review = deepcopy(review)
            saved_review["technical_requirements"] = [{**row, "translation_status": "translated", "need_human_review": True,
                "translation_output_snapshot": {"content": row["content"], "type": row["type"]}} for row in fixtures]
            saved = repository.save_review("order", saved_review, expected_revision=1, owner=owner)
            assert saved["revision"] == 2
            reopened = repository.get_review("order", owner_user_id=owner["user_id"])["review"]
            assert reopened["technical_requirements"] == saved_review["technical_requirements"]
            assert all(not translation_blocks_export(note) for note in reopened["technical_requirements"])
            try:
                repository.save_review("order", review, expected_revision=1, owner=owner)
                raise AssertionError("A stale save must not overwrite current output snapshots")
            except RevisionConflictError:
                pass
        finally:
            repository.dispose()
    assert len(calls) == 1
    print("PASS: six shared direct results, three screenshot candidates, legacy success, no loops, confirmation and frozen SW")


if __name__ == "__main__":
    run()
