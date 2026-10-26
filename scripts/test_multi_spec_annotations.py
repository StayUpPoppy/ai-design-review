"""Offline scoped locations: repeated common values, legacy refresh and races."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["AI_REVIEW_MOCK_USER_ID"] = "annotation-test-user"
os.environ["AI_REVIEW_MOCK_USERNAME"] = "annotation-test-user"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient
from PIL import Image
from ai_design_review import api
from ai_design_review.drawing_annotations import (ALGORITHM_VERSION, annotation_source, build_annotations,
    locate_fields, merge_annotation_upgrade, roughness_refresh_key)
from ai_design_review.engines.ocr_providers import RapidOcrProvider
from ai_design_review.annotation_ocr import local_ocr_blocks
from ai_design_review.io_utils import write_json
from ai_design_review.multi_spec import (annotation_context, child_review, link_assets, location_policy,
    parse_multi_spec, source_review)
from ai_design_review.review_persistence import ReviewPersistence

VALUES = {"wire_diameter": 14, "mean_diameter": 66, "active_coils": 20, "total_coils": 22, "solid_height": 308, "free_length": 607}
LABELS = {"wire_diameter": "簧丝直径d", "mean_diameter": "中径D", "active_coils": "有效圈数n", "total_coils": "总圈数n1", "solid_height": "压并高度", "free_length": "自由高度H0"}
OWNER = {"user_id": "annotation-test-user", "username": "annotation-test-user"}


def block(text, x, y, width=.04, height=.025, page=1, **extra):
    return {"text": text, "position": {"x": x, "y": y, "width": width, "height": height}, "page": page, "source": "ocr", **extra}


def fixture():
    p = {"document_mode": "multi", "layout": "blocks", "complete": True, "spec_count": 3,
         "drawing_summary": {"drawing_name": "三分区表格"},
         "common": {"applies_to_all": True, "parameters": {k: {"value": v, "unit": "mm", "evidence": f"{LABELS[k]} {v}"} for k, v in VALUES.items() if k != "free_length"}},
         "variants": [{"page": 1, "region": {"x": i/3, "y": 0, "width": 1/3, "height": .9},
                       "parameters": {"free_length": {"value": 607, "unit": "mm", "evidence": "自由高度H0 607"}}} for i in range(3)]}
    source = source_review(p, parse_multi_spec(p))
    blocks = []
    for i in range(3):
        for j, field in enumerate(VALUES):
            blocks += [block(LABELS[field], i/3+.01, .06+j*.08, .12), block(str(VALUES[field]), i/3+.19, .06+j*.08)]
    return source, blocks


def located(review, candidates, blocks):
    return {a["field"]: a for a in locate_fields(review, candidates, blocks)}


def check_scope():
    source, blocks = fixture()
    for index, candidate in enumerate(source["multi_spec"]["variants"]):
        review, candidates = child_review(source, candidate, "source")
        before = deepcopy(review)
        # New and old common-without-regions children follow the same safe rule.
        for legacy in (False, True):
            value = deepcopy(review)
            if legacy:
                for key in ("field_origins", "layout", "source_context", "specification_regions"):
                    value["multi_spec_origin"].pop(key)
                for key in VALUES:
                    if key != "free_length": value["multi_spec_origin"]["field_regions"][key] = []
            result = located(value, candidates, blocks)
            for field in VALUES:
                assert len(result[field]["locations"]) == 1, (index, field, result[field])
                assert index/3 < result[field]["locations"][0]["anchor"]["x"] < (index+1)/3
            assert not result["outer_diameter"]["locations"]
            assert not result["inner_diameter"]["locations"]
        assert review == before
    review, candidates = child_review(source, source["multi_spec"]["variants"][0], "source")
    # A scalar alone, or a matching model box without a label, cannot locate.
    one = block("14", .2, .1, input_size=[1000, 1000])
    candidates = deepcopy(candidates)
    next(c for c in candidates if c["field"] == "wire_diameter")["position"] = {**one["position"], "coordinate_type": "normalized", "origin": "top_left"}
    assert not located(review, candidates, [one])["wire_diameter"]["locations"]
    # An otherwise convincing wrong-column match is never borrowed.
    assert not located(review, candidates, blocks[12:])["wire_diameter"]["locations"]
    # Same value on the wrong parameter row cannot become a second anchor.
    wrong_row = [block("弹力", .01, .7, .12), block("14", .19, .7)]
    assert len(located(review, candidates, blocks + wrong_row)["wire_diameter"]["locations"]) == 1
    ambiguous = blocks + [block("簧丝直径d", .01, .7, .12), block("14", .19, .7)]
    assert not located(review, candidates, ambiguous)["wire_diameter"]["locations"]
    # Duplicate readings of the same glyph do not make it ambiguous.
    assert len(located(review, candidates, blocks + deepcopy(blocks))["wire_diameter"]["locations"]) == 1
    missing_region = deepcopy(review); missing_region["multi_spec_origin"]["region"] = None
    assert not located(missing_region, candidates, blocks)["wire_diameter"]["locations"]
    wrong_region = deepcopy(review); wrong_region["multi_spec_origin"]["code"] = "FTA-10/85-260"
    conflict = located(wrong_region, candidates, blocks + [block("FTA-10/85-260", .5, .65, .1)])
    assert not conflict["wire_diameter"]["locations"] and "代号位置不一致" in conflict["wire_diameter"]["reason"]
    # Full OCR runs spanning columns or rows cannot supply guessed digit boxes.
    cross = block("簧丝直径d 14", .1, .1, .4)
    assert not located(review, candidates, [cross])["wire_diameter"]["locations"]
    # Even a token inside the region cannot inherit a label outside it.
    cross["tokens"] = [{"text": "14", "position": one["position"]}]
    assert not located(review, candidates, [cross])["wire_diameter"]["locations"]
    # Explicit public evidence is a fallback, not another location for a repeat.
    common = block("14", .2, .94); label = block("簧丝直径d", .01, .94, .12)
    review["multi_spec_origin"]["common_regions"] = [{"page": 1, "x": 0, "y": .9, "width": .32, "height": .1}]
    own = located(review, candidates, blocks + [common, label])["wire_diameter"]["locations"]
    assert len(own) == 1 and own[0]["anchor"]["y"] < .9
    public = located(review, candidates, [common, label])["wire_diameter"]["locations"]
    assert len(public) == 1 and public[0]["anchor"]["y"] > .9
    # A declared common region covering another specification is not public.
    review["multi_spec_origin"]["common_regions"] = [review["multi_spec_origin"]["specification_regions"][1]]
    assert not located(review, candidates, blocks[12:])["wire_diameter"]["locations"]
    # Common evidence may be on another page, but numbers on any other page may not.
    review["multi_spec_origin"]["common_regions"] = [{"page": 2, "x": 0, "y": .9, "width": .32, "height": .1}]
    for b in (common, label): b["page"] = 2
    assert located(review, candidates, [common, label])["wire_diameter"]["locations"][0]["page"] == 2
    assert not located(review, candidates, [{**b, "page": 3} for b in (common, label)])["wire_diameter"]["locations"]
    prior = {"algorithm_version": ALGORITHM_VERSION, "source_document_id": "same", "annotation_revision": 2,
             "annotations": locate_fields(review, candidates, blocks)}
    wire = next(a for a in prior["annotations"] if a["field"] == "wire_diameter")
    wire["locations"][0].update(source="legacy_unknown", anchor={"x": .8, "y": .5})
    rebuilt = deepcopy(prior); rebuilt["multi_spec_location"] = location_policy(review)
    next(a for a in rebuilt["annotations"] if a["field"] == "wire_diameter")["locations"] = []
    merged = merge_annotation_upgrade(prior, rebuilt, force=True)
    assert next(a for a in merged["annotations"] if a["field"] == "wire_diameter")["locations"] == wire["locations"], "unknown historical sources remain protected"


def check_rows():
    rows = [{"page": 1, "x": .05, "y": .25+i*.04, "width": .9, "height": .035} for i in range(13)]
    headers = [block("有效", .25, .11, .03), block("圈数", .25, .15, .03), block("总圈数", .4, .11, .04)]
    values = [b for i in range(13) for b in (block("10", .25, .255+i*.04, .03), block("12", .4, .255+i*.04, .03))]
    for index in range(13):
        review = {"drawing_summary": {"spring_type": "compression_spring"},
                  "spring_parameters": {"active_coils": {"value": 10, "source": ["qwen_vision"]}, "total_coils": {"value": 12, "source": ["qwen_vision"]}},
                  "multi_spec_origin": {"layout": "rows", "region": rows[index], "specification_regions": rows, "field_origins": {"active_coils": "local", "total_coils": "local"}}}
        result = located(review, [], headers + values)
        for field in ("active_coils", "total_coils"):
            locs = result[field]["locations"]
            assert len(locs) == 1 and rows[index]["y"] < locs[0]["anchor"]["y"] < rows[index]["y"]+rows[index]["height"], (index, result)
        assert not located(review, [], values)["active_coils"]["locations"], "unknown column cannot be inferred from scalar value"
    # An unknown D1 column cannot establish an outer/inner diameter role.
    review["spring_parameters"]["outer_diameter"] = {"value": 75, "source": ["qwen_vision"]}
    assert not located(review, [], headers + values + [block("D1", .6, .15), block("75", .6, rows[-1]["y"]+.005)])["outer_diameter"]["locations"]


def check_cache_budget():
    source, _ = fixture()
    with tempfile.TemporaryDirectory() as directory:
        d = Path(directory); (d/"pages").mkdir()
        Image.new("RGB", (1200, 700), "white").save(d/"pages"/"page-1.png")
        cache = {"algorithm_version": ALGORITHM_VERSION, "source_document_id": "cache-test", "cache_format": 4,
                 "blocks": [block("unrelated", .9, .95)], "full": {"1": "completed"}, "regions": {},
                 "handled_fields": {"1": list(VALUES)}, "warnings": []}
        write_json(d/"annotation_ocr_v3.json", cache)
        calls = []
        def ocr(paths, _):
            assert 0 < len(paths) <= 12
            calls.append(paths)
            return [{"page": i+1, "image_path": str(p), "texts": []} for i, p in enumerate(paths)]
        pages = [{"page": 1, "width": 1200, "height": 700}]
        with patch.object(RapidOcrProvider, "recognize", side_effect=ocr), patch("ai_design_review.annotation_ocr.crop_regions", return_value=[]):
            for candidate in source["multi_spec"]["variants"][:2]:
                review, candidates = child_review(source, candidate, "source")
                local_ocr_blocks(d, pages, "cache-test", review, candidates, [])
                assert len(calls) == candidate["order"], "one child's handled fields cannot suppress another child's crops"
                local_ocr_blocks(d, pages, "cache-test", review, candidates, [])
                assert len(calls) == candidate["order"], "completed regions and scope requests must be reused"
        result = json.loads((d/"annotation_ocr_v3.json").read_text())
        assert result["full"] == {"1": "completed"} and result["blocks"] == cache["blocks"]
        assert len(result["regions"]) == 6


def check_api():
    old_repo, old_root = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); repository = ReviewPersistence(f"sqlite+pysqlite:///{root/'reviews.db'}"); repository.create_schema_for_testing()
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = repository, root
        try:
            source, blocks = fixture()
            for name in ("legacy", "race", "retry", "failure"):
                source_id = f"source{name}"; source_dir = root/source_id
                (source_dir/"inputs").mkdir(parents=True); (source_dir/"pages").mkdir()
                Image.new("RGB", (1200, 700), "white").save(source_dir/"inputs"/"source.png")
                Image.new("RGB", (1200, 700), "white").save(source_dir/"pages"/"source.png")
                write_json(source_dir/"review.json", source)
                repository.create_review(source_id, source, artifact_dir=str(source_dir), owner=OWNER)
                review, candidates = child_review(source, source["multi_spec"]["variants"][0], source_id)
                for key in ("field_origins", "layout", "source_context", "specification_regions"):
                    review["multi_spec_origin"].pop(key)
                review["multi_spec_origin"]["field_regions"] = {k: [] if k != "free_length" else [review["multi_spec_origin"]["region"]] for k in VALUES}
                d = root/name; link_assets(source_dir, d, candidates); write_json(d/"review.json", review)
                doc, _ = annotation_source(d, lambda p: api._artifact_url(name, p))
                cache = {"algorithm_version": ALGORITHM_VERSION, "source_document_id": doc["source_document_id"], "cache_format": 4,
                         "blocks": blocks, "full": {"1": "completed"}, "regions": {}, "handled_fields": {"1": list(VALUES)}, "warnings": []}
                write_json(source_dir/"annotation_ocr_v3.json", cache)
                # Reproduce the existing document with only the height located.
                doc["annotations"] = locate_fields(review, candidates, blocks)
                for a in doc["annotations"]:
                    if a["field"] != "free_length": a.update(locations=[], status="unlocated")
                doc["roughness_evidence_signature"] = roughness_refresh_key(review)
                doc["annotation_revision"] = 3
                if name == "retry":
                    # A stale automatic location points to the neighbouring block.
                    a = next(a for a in doc["annotations"] if a["field"] == "free_length")
                    a["locations"][0]["anchor"]["x"] = .55
                review["drawing_annotations"] = doc
                repository.create_review(name, review, artifact_dir=str(d), owner=OWNER)
            with TestClient(api.app) as client, patch.object(api, "verify_review_roughness", return_value=None), patch.object(RapidOcrProvider, "recognize", side_effect=AssertionError("saved OCR must be reused")):
                baseline = repository.get_review("legacy", owner_user_id=OWNER["user_id"])
                real_build = api.build_annotations
                with patch.object(api, "build_annotations", wraps=real_build) as build:
                    result = client.get("/api/reviews/legacy/annotations"); assert result.status_code == 200, result.text
                    document = result.json()
                    assert document["multi_spec_location"]["version"] == "multi-spec-locator/v2"
                    assert document["annotation_revision"] == 4
                    assert all(next(a for a in document["annotations"] if a["field"] == f)["locations"] for f in VALUES)
                    assert client.get("/api/reviews/legacy/annotations").json() == document
                    assert build.call_count == 1
                after = repository.get_review("legacy", owner_user_id=OWNER["user_id"])
                assert after["revision"] == baseline["revision"] == 1
                for value in (baseline["review"], after["review"]): value.pop("drawing_annotations")
                assert after["review"] == baseline["review"]
                # A concurrent manual move wins over the old build snapshot.
                expected = {}
                def racing_builder(*args, **kwargs):
                    rebuilt = real_build(*args, **kwargs)
                    current = repository.get_review("race", owner_user_id=OWNER["user_id"])["review"]["drawing_annotations"]
                    loc = deepcopy(next(a for a in current["annotations"] if a["field"] == "free_length")["locations"][0])
                    expected.update({"annotation_id": "free_length", "location_id": loc["location_id"], "page": 1, "anchor": {"x": .17, "y": .3}, "bubble": {"x": .22, "y": .25}})
                    repository.save_drawing_annotations("race", owner_user_id=OWNER["user_id"], patch={"source_document_id": current["source_document_id"], "expected_annotation_revision": 3, "changes": [expected]})
                    return rebuilt
                with patch.object(api, "build_annotations", side_effect=racing_builder):
                    race = client.get("/api/reviews/race/annotations").json()
                manual = next(a for a in race["annotations"] if a["field"] == "free_length")["locations"]
                assert any(l["source"] == "manual" and l["anchor"] == expected["anchor"] for l in manual)
                assert race["annotation_revision"] == 5
                again = client.post("/api/reviews/race/annotations/relocalize", json={"source_document_id": race["source_document_id"], "expected_annotation_revision": race["annotation_revision"]})
                assert again.status_code == 200
                assert any(l["source"] == "manual" and l["anchor"] == expected["anchor"] for l in next(a for a in again.json()["annotations"] if a["field"] == "free_length")["locations"])
                # Relocalize replaces wrong automatic anchors but keeps manual ones.
                retry = client.get("/api/reviews/retry/annotations").json()
                response = client.post("/api/reviews/retry/annotations/relocalize", json={"source_document_id": retry["source_document_id"], "expected_annotation_revision": retry["annotation_revision"]})
                assert response.status_code == 200, response.text
                assert next(a for a in response.json()["annotations"] if a["field"] == "free_length")["locations"][0]["anchor"]["x"] < 1/3
                with patch.object(api, "build_annotations", side_effect=RuntimeError("simulated local failure")) as build:
                    failed = client.get("/api/reviews/failure/annotations").json()
                    assert failed["multi_spec_location"] and failed["warnings"]
                    assert client.get("/api/reviews/failure/annotations").json() == failed
                    assert build.call_count == 1
                # Normal single records do not need a new strategy marker or rebuild.
                ordinary = deepcopy(repository.get_review("legacy", owner_user_id=OWNER["user_id"])["review"])
                ordinary.pop("multi_spec_origin"); ordinary["record_kind"] = "single"
                ordinary["drawing_annotations"].pop("multi_spec_location")
                ordinary["drawing_annotations"]["roughness_evidence_signature"] = roughness_refresh_key(ordinary)
                repository.create_review("single", ordinary, artifact_dir=str(root/"legacy"), owner=OWNER)
                with patch.object(api, "build_annotations", side_effect=AssertionError("ordinary record must not rebuild")):
                    assert client.get("/api/reviews/single/annotations").status_code == 200
        finally:
            api.REVIEW_PERSISTENCE, api.API_RUN_ROOT = old_repo, old_root
            repository._engine.dispose()


def check_saved_response():
    path = Path(__file__).resolve().parents[1]/"outputs/multi-spec-annotation-qa/saved.json"
    if not path.exists(): return
    saved = json.loads(path.read_text(encoding="utf-8-sig"))
    for item in saved["children"]:
        review = item["review"]; before = deepcopy(review)
        result = located(review, item["candidates"]["candidates"], saved["ocr"]["blocks"])
        r = review["multi_spec_origin"]["region"]
        for field in VALUES:
            locs = result[field]["locations"]
            assert len(locs) == 1 and r["x"] < locs[0]["anchor"]["x"] < r["x"]+r["width"], (field, locs)
        assert review == before
    print("PASS actual saved Qwen/OCR replay: all 3 children recover 6 field anchors inside their own blocks")
    rows_path = path.parent/"rows-saved.json"
    if rows_path.exists():
        rows = json.loads(rows_path.read_text(encoding="utf-8-sig"))
        first = rows["source"]["multi_spec"]["variants"][0]
        review, candidates = child_review(rows["source"], first, "source")
        result = located(review, candidates, rows["ocr"]["blocks"])
        assert not result["active_coils"]["locations"] and "代号位置不一致" in result["active_coils"]["reason"]
        print("PASS old 13-row source: reversed model regions are rejected by independently read specification code, never guessed or borrowed")
    # The upload/child pipeline must also work with no saved annotations.
    image_path = Path("C:/Users/29580/Desktop/多规格1.png")
    if image_path.exists():
        qa = path.parent; (qa/"source.png").write_bytes(image_path.read_bytes())
        cases = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source_dir = root/"source"
            (source_dir/"inputs").mkdir(parents=True); (source_dir/"pages").mkdir()
            for folder in ("inputs", "pages"): (source_dir/folder/"source.png").write_bytes(image_path.read_bytes())
            write_json(source_dir/"review.json", saved["source"])
            for index, variant in enumerate(saved["source"]["multi_spec"]["variants"]):
                review, candidates = child_review(saved["source"], variant, "source")
                assert "drawing_annotations" not in review
                job_id = f"fresh{index}"; d = root/job_id; link_assets(source_dir, d, candidates)
                url = lambda p: f"/api/reviews/{job_id}/artifacts/{p.as_posix()}"
                document, _ = annotation_source(d, url)
                cache = {**saved["ocr"], "source_document_id": document["source_document_id"]}
                write_json(source_dir/"annotation_ocr_v3.json", cache)
                before = deepcopy(review)
                with patch.object(RapidOcrProvider, "recognize", side_effect=AssertionError("new child reuses saved OCR")):
                    document = build_annotations(review, d, url)
                assert review == before
                assert all(next(a for a in document["annotations"] if a["field"] == f)["locations"] for f in VALUES)
                browser_review = deepcopy(review)
                api.ensure_compression_material(browser_review)
                api.ensure_surface_roughness_parameter(browser_review)
                api.apply_generation_defaults(browser_review)
                api._prepare_review_reasonableness(browser_review, 1)
                # Isolate viewer gestures from the existing one-time formula
                # reconciliation audit that a fresh review records on opening.
                adjustment = browser_review["spring_parameters"].get("support_coils", {}).get("support_coils_adjustment")
                if adjustment: adjustment["audit_recorded"] = True
                cases.append({"id": job_id, "review": browser_review, "annotations": document})
        write_json(qa/"browser.json", cases)
        print("PASS fresh children: full builder restores all 6 locations without history, Qwen or another OCR call")


if __name__ == "__main__":
    check_scope(); check_rows(); check_cache_budget(); check_api(); check_saved_response()
    print("PASS multi-spec scoped labels, 13 rows, no cross-spec anchors, cache reuse, legacy upgrade, manual race, retry and unchanged engineering revisions")
