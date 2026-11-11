"""Offline provenance, candidate-only persistence and generation regressions."""
from __future__ import annotations

import json
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from ai_design_review.diameter_evidence import (
    CANDIDATE, INFERENCE, PENDING, has_pending_roles, ignore_role, model_derived_diameter, pending_roles,
    resolve_diameter_roles, select_role,
)


def mark(value=12, evidence="图形标注 Ø12（尺寸界线指向弹簧外缘）", **extra):
    return {"field": CANDIDATE, "candidate_id": f"mark-{value}", "value": value, "unit": "mm",
            "source": "qwen_vision", "page": 1, "evidence": evidence, **extra}


def grounded(value=12, evidence=None):
    position={"x":.2,"y":.3,"width":.06,"height":.02,"coordinate_type":"normalized"}
    return mark(value,evidence or f"Φ{value}",position=position,diameter_role_evidence={
        "observation":{"source":"local_ocr","value":value,"page":1,"position":position,"text":f"Φ{value}"}})


def provenance_fixtures():
    fixtures = [(mark(), False)]
    for text in (
        "计算值：外径12 - 线径1.6 = 10.4", "计算结果：12－1.6＝10.4", "12 - 1.6 = 10.4",
        "推算中径Φ10.4", "中径Φ10.4（计算值）", "由外径12减线径1.6推算，原图未标注中径",
        "图中标注Φ12，由12 - 1.6 = 10.4推得中径", "computed mean diameter 10.4",
        "中径10.4（外径12减线径1.6）", "D = Do - d", "中径＝外径－线径",
    ):
        fixtures.append((mark(10.4, text), True))
    fixtures += [
        (mark(12, "图中标注φ12，结合线径1.6推算中径10.4"), False),
        (mark(12, "根据原图Φ12计算中径10.4"), False),
        (mark(10.4, "图中标注φ10.4，结合线径1.6推算其他尺寸"), False),
        (mark(10.4, "D = Do - d", source=["formula_calculation"]), True),
        (mark(10.4, "计算值：12-1.6=10.4", diameter_role_evidence={"observation": {"source": "local_ocr", "value": 10.4}}), False),
        (mark(10.4, "计算值：12-1.6=10.4", diameter_role_evidence={"observation": {"source": "qwen_vision", "value": 10.4}}), True),
    ]
    bare=grounded(175)
    bare["diameter_role_evidence"]["observation"]["text"]="175"
    return [{"candidate": item, "derived": expected, "eligible": False} for item, expected in fixtures] + [
        {"candidate":bare,"derived":False,"eligible":False},
        {"candidate":grounded(111,"假设 Φ175。等等，原图标的是 Φ111。"*50),"derived":False,"eligible":True}]


class ProvenanceTests(unittest.TestCase):
    def test_same_source_rules_for_new_and_saved_candidates(self):
        for fixture in provenance_fixtures():
            item, expected = fixture["candidate"], fixture["derived"]
            with self.subTest(evidence=item["evidence"]):
                before = deepcopy(item)
                self.assertEqual(model_derived_diameter(item), expected)
                self.assertEqual(has_pending_roles({PENDING: [item]}), fixture["eligible"])
                self.assertEqual(item, before, "Historical filtering must not mutate its input")

    def test_screenshot_candidates_keep_original_and_exclude_model_result(self):
        original = {**mark(), "field": "outer_diameter"}
        derived = {**mark(10.4, "计算值：外径12 - 线径1.6 = 10.4"), "field": "mean_diameter"}
        page={"page":1,"width":400,"height":300,"source":"pdf_text_layer","lines":[],"line_segments":[],
              "texts":[{"text":"Φ12","bbox":[80,90,104,96]}]}
        records = resolve_diameter_roles([original, derived],[page])
        self.assertEqual([item["field"] for item in records], [CANDIDATE, INFERENCE])
        self.assertEqual(records[0]["value"], 12)
        self.assertEqual(records[1]["value"]["value"], 10.4)
        self.assertEqual(resolve_diameter_roles([mark(10.4, derived["evidence"])])[0]["field"], INFERENCE)
        invented={**mark(175,"图纸上标的肯定是175。Φ111+2/0。外径=111+64=175。"*50),"field":"outer_diameter"}
        actual={**mark(111,"尺寸标注 Φ111"),"field":"mean_diameter"}
        page["texts"]=[{"text":"Φ111+2/0","bbox":[80,90,104,96]}]
        actual_records=resolve_diameter_roles([invented,actual],[page])
        grounded_record=next(item for item in actual_records if item["field"]==CANDIDATE)
        self.assertEqual((grounded_record["value"],grounded_record["tolerance_upper"],grounded_record["tolerance_lower"]),(111,2,0))
        self.assertEqual(grounded_record["evidence"],"Φ111+2/0")
        self.assertEqual(len(pending_roles({PENDING:actual_records})),1)

    def test_selected_and_ignored_history_is_preserved(self):
        selected = mark(10.4, "计算值：12-1.6=10.4", selected_field="mean_diameter")
        review = {PENDING: [selected, mark(13, "Φ13", ignored=True), grounded()]}
        before = deepcopy(review)
        self.assertEqual([item["value"] for item in pending_roles(review)], [12])
        self.assertEqual(review, before)
        with self.assertRaises(ValueError):
            ignore_role(review, selected["candidate_id"])
        ignore_role(review, "mark-12")
        ignore_role(review, "mark-12")
        self.assertFalse(has_pending_roles(review))
        with self.assertRaises(ValueError):
            select_role(review, "mark-12", "outer_diameter")


class CandidateApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from scripts.test_solidworks_push_api import api, OWNER, ready_review
        from ai_design_review.review_persistence import ReviewPersistence
        from ai_design_review.review_loading import VERSION
        self.api, self.owner = api, OWNER
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = ReviewPersistence(f"sqlite+pysqlite:///{self.root / 'review.db'}")
        self.repo.create_schema_for_testing()
        self.review = ready_review()
        from ai_design_review.flattening import ensure
        ensure(self.review)
        self.review[PENDING] = [grounded(), grounded(14, "图中标注Φ14")]
        self.review["local_verification"] = {"version": VERSION}
        self.review["manual_confirmations"] = {"wire_diameter": {"confirmed": True}}
        self.review["diameter_linkage"] = {"version": "test-frozen", "status": "calculated", "inputs": {"test": 1}}
        self.repo.create_review("candidate", self.review, owner=OWNER)
        (self.root / "candidate").mkdir()
        from ai_design_review.io_utils import write_json
        write_json(self.root / "candidate" / "review.json", self.review)
        self.patcher = patch.multiple(api, REVIEW_PERSISTENCE=self.repo, API_RUN_ROOT=self.root,
            verify_review_roughness=lambda *a, **kw: None)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(api.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.url = "/api/reviews/candidate"

    def stored(self):
        return self.repo.get_review("candidate", owner_user_id=self.owner["user_id"])

    def edit(self, candidate_id="mark-12", **extra):
        current = self.client.get(self.url).json()
        return {"review": current, "expected_revision": current.get("review_revision"), "events": [{
            "event_type": "diameter_role_ignored", "client_event_id": f"ignore-{candidate_id}",
            "metadata": {"candidate_id": candidate_id}}], **extra}

    def test_ignore_is_candidate_only_and_survives_reopen_and_retry(self):
        before = self.stored()
        body = self.edit()
        body["review"]["spring_parameters"]["wire_diameter"]["value"] = 999
        body["review"][PENDING][1]["ignored"] = True
        response = self.client.patch(self.url, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        update = response.json()["diameter_role_update"]
        self.assertTrue(update["candidates_only"])
        self.assertNotIn("parameters", update)
        self.assertTrue(update["candidates"][0]["ignored"])
        self.assertNotIn("ignored", update["candidates"][1])
        after = self.stored()
        for key in ("spring_parameters", "manual_confirmations", "diameter_linkage", "technical_requirements", "standardization_results"):
            self.assertEqual(after["review"][key], before["review"][key], key)
        self.assertTrue(self.client.get(self.url).json()[PENDING][0]["ignored"])
        repeated = self.client.patch(self.url, json=body)
        self.assertEqual(repeated.status_code, 409, "A lost receipt must reconcile before accepting a newer revision")
        body["expected_revision"] = after["revision"]
        repeated = self.client.patch(self.url, json=body)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["review_revision"], after["revision"])
        events = self.repo.list_change_events("candidate", owner_user_id=self.owner["user_id"])
        self.assertEqual(sum(event["event_type"] == "diameter_role_ignored" for event in events), 1)

    def test_missing_id_and_selected_candidate_cannot_be_ignored(self):
        self.assertEqual(self.client.patch(self.url, json=self.edit("missing")).status_code, 422)
        body = self.edit(None)
        self.assertEqual(self.client.patch(self.url, json=body).status_code, 422)
        stale = self.edit()
        stored = self.stored()
        stored["review"][PENDING][0]["selected_field"] = "outer_diameter"
        self.repo.save_review("candidate", stored["review"], expected_revision=stored["revision"], owner=self.owner)
        before = self.stored()
        self.assertEqual(self.client.patch(self.url, json=stale).status_code, 409)
        self.assertEqual(self.client.patch(self.url, json=self.edit()).status_code, 422)
        self.assertEqual(self.stored()["review"], before["review"])

    def test_revision_conflict_does_not_erase_new_parameters(self):
        body = self.edit()
        current = self.stored()
        current["review"]["spring_parameters"]["outer_diameter"]["value"] = 34
        self.repo.save_review("candidate", current["review"], expected_revision=current["revision"], owner=self.owner)
        self.assertEqual(self.client.patch(self.url, json=body).status_code, 409)
        response = self.client.patch(self.url, json=self.edit())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored()["review"]["spring_parameters"]["outer_diameter"]["value"], 34)

    def test_mixed_manual_edit_and_ignore_keep_both_changes(self):
        stored = self.stored()
        stored["review"].pop("diameter_linkage")
        self.repo.save_review("candidate", stored["review"], expected_revision=stored["revision"], owner=self.owner)
        body = self.edit()
        body["review"]["spring_parameters"]["outer_diameter"].update(value=34, need_human_review=True)
        body["events"].append({"event_type": "parameter_value_updated", "target_field": "outer_diameter", "client_event_id": "manual-outer"})
        response = self.client.patch(self.url, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        review = self.stored()["review"]
        self.assertTrue(review[PENDING][0]["ignored"])
        self.assertEqual(review["spring_parameters"]["outer_diameter"]["value"], 34)
        self.assertTrue(review["spring_parameters"]["outer_diameter"]["need_human_review"])
        self.assertEqual(review["spring_parameters"]["mean_diameter"]["value"], 31)

    def test_other_owner_and_forged_candidate_list_cannot_ignore(self):
        body = self.edit()
        with patch.dict(os.environ, {"AI_REVIEW_MOCK_USER_ID": "another-user"}):
            self.assertEqual(self.client.patch(self.url, json=body).status_code, 404)
        body["review"][PENDING].append(mark(99, "Φ99"))
        body["events"][0]["metadata"]["candidate_id"] = "mark-99"
        self.assertEqual(self.client.patch(self.url, json=body).status_code, 422)
        self.assertNotIn("ignored", self.stored()["review"][PENDING][0])

    def test_json_fallback_preserves_parameters_and_saves_ignore(self):
        from ai_design_review.review_persistence import ReviewPersistence
        from ai_design_review.io_utils import read_json, write_json
        directory = self.root / "candidate"
        write_json(directory / "owner.json", self.owner)
        before = read_json(directory / "review.json")
        with patch.object(self.api, "REVIEW_PERSISTENCE", ReviewPersistence("")):
            body = self.edit()
            response = self.client.patch(self.url, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            after = read_json(directory / "review.json")
            self.assertTrue(after[PENDING][0]["ignored"])
            self.assertEqual(after["spring_parameters"], before["spring_parameters"])
            self.assertEqual(self.client.patch(self.url, json=body).status_code, 200)
            self.assertEqual(len(read_json(directory / "review.json")["change_history"]), 1)

    def test_historical_filter_is_read_only_and_changes_generation_cache(self):
        from ai_design_review.review_loading import cached_readiness, _readiness_cache
        from ai_design_review.identity import IdentityContext
        current = self.stored()
        current["review"][PENDING] = [mark(10.4, "计算值：外径12 - 线径1.6 = 10.4")]
        self.repo.save_review("candidate", current["review"], expected_revision=current["revision"], owner=self.owner)
        before = deepcopy(self.stored())
        self.client.get(self.url)
        self.client.get(self.url + "/generation-readiness")
        self.assertEqual(self.stored(), before)
        identity = IdentityContext(**self.owner, source="test")
        review = deepcopy(before["review"])
        review[PENDING] = [grounded()]
        _readiness_cache.clear()
        with patch("ai_design_review.generation_readiness.assess_generation_readiness", side_effect=lambda r: {"blocked": has_pending_roles(r)}):
            self.assertTrue(cached_readiness("candidate", 7, identity, review)["blocked"])
            ignore_role(review, "mark-12")
            self.assertFalse(cached_readiness("candidate", 7, identity, review)["blocked"])

    def test_ignored_candidate_does_not_bypass_parameter_checks(self):
        from ai_design_review.generation_readiness import assess_generation_readiness
        baseline = deepcopy(self.review)
        baseline.pop("diameter_linkage")
        baseline[PENDING] = []
        expected = assess_generation_readiness(deepcopy(baseline))
        baseline[PENDING] = [mark(ignored=True)]
        self.assertEqual(assess_generation_readiness(deepcopy(baseline)), expected)
        for value in (None, 0):
            broken = deepcopy(baseline)
            broken["spring_parameters"]["wire_diameter"]["value"] = value
            self.assertNotIn(assess_generation_readiness(broken)["status"], ("ready", "ready_with_warnings"))
        baseline["spring_parameters"]["wire_diameter"]["need_human_review"] = True
        self.assertNotIn(assess_generation_readiness(baseline)["status"], ("ready", "ready_with_warnings"))


if __name__ == "__main__":
    if "--json" in sys.argv:
        print(json.dumps(provenance_fixtures(), ensure_ascii=False))
    else:
        unittest.main()
