"""Offline multi-spec contracts, transaction/retry/ownership and legacy migration."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER
from fastapi.testclient import TestClient
from ai_design_review.multi_spec import parse_multi_spec, source_review, child_review, MultiSpecError, restrict_blocks
from ai_design_review import multi_spec_store as store
from ai_design_review.review_persistence import ReviewPersistence


def parameter(value, unit="mm", **kw): return {"value": value, "unit": unit, **kw}


def fixture(count=3):
    # Repeated blocks in attachment 1; block loads stay separate even with identical geometry.
    return {"document_mode": "multi", "layout": "blocks" if count == 3 else "rows", "complete": True, "spec_count": count,
        "drawing_summary": {"drawing_name": "多规格压缩弹簧", "drawing_no": "001-原图"},
        "common": {"applies_to_all": True, "parameters": {"material": parameter("50CrVA", None)}, "technical_requirements": [], "regions": []},
        "variants": [{"code": f"S{i+1}", "page": 1, "region": {"x": i/count, "y": 0, "width": 1/count, "height": .95},
            "parameters": {"wire_diameter": parameter(14), "mean_diameter": parameter(66), "free_length": parameter(607), "total_coils": parameter(22, "圈"), "active_coils": parameter(20, "圈")},
            "load_points": [{"label": "F1", "deflection": [147,137,114][i%3], "deflection_unit": "mm", "force": [9698.504675,9038.742452,7521.28934][i%3], "force_unit": "N"}],
            "source_context": {"row_text": f"独立区块{i+1}", "headers": ["压缩变形量 mm", "载荷 N"]}, "reference_values": {"stress": 791.4656}} for i in range(count)]}


def expect_error(fn, status):
    try: fn()
    except store.VariantStoreError as exc: assert exc.status == status, exc
    else: raise AssertionError("Expected rejection")


def main():
    payload = fixture(); multi = parse_multi_spec(payload, 1); source = source_review(payload, multi)
    assert len({v["variant_id"] for v in multi["variants"]}) == 3
    child, candidates = child_review(source, multi["variants"][0], "source")
    params = child["spring_parameters"]
    assert params["outer_diameter"]["value"] == 80 and params["inner_diameter"]["value"] == 52, params
    assert params["free_length"]["value"] == 607 and params["mean_diameter"]["value"] == 66
    assert params["wire_diameter"]["need_human_review"]
    assert params["load_points"][0]["height"] == 460, params["load_points"]
    assert child["drawing_summary"]["drawing_no"] == "001-原图"
    assert child["multi_spec_origin"]["reference_values"]["stress"] == 791.4656
    calculated = fixture(); calculated["common"]["parameters"]["spring_rate"] = parameter(999,"N/mm")
    checked_source = source_review(calculated,parse_multi_spec(calculated))
    checked,_ = child_review(checked_source,checked_source["multi_spec"]["variants"][0],"source")
    assert checked["spring_parameters"]["spring_rate"]["value"] != 999
    assert checked["multi_spec_origin"]["reference_values"]["spring_rate"]["value"] == 999
    for invalid in ({"complete": False}, {"spec_count": 4}, {"variants": fixture(51)["variants"]}, {"document_mode": "uncertain"}):
        try: parse_multi_spec({**payload, **invalid}, 1)
        except MultiSpecError: pass
        else: raise AssertionError(invalid)
    assert parse_multi_spec({"parameters": {}, "load_points": [{},{}]}) is None
    assert len(parse_multi_spec(fixture(13))["variants"]) == 13
    wrong = deepcopy(multi["variants"][0]); wrong["load_points"][0].pop("deflection_unit")
    incomplete, _ = child_review(source, wrong, "source")
    assert incomplete["spring_parameters"]["load_points"][0]["height"] is None
    assert incomplete["multi_spec_origin"]["issues"]
    blocks = [{"text":"14", "page":1, "position":{"x":x,"y":.4,"width":.01,"height":.01}} for x in [.05,.5,.9]]
    assert len(restrict_blocks(child, blocks, "wire_diameter")) == 1
    old_repo, old_root, old_verify = api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); repo = ReviewPersistence(f"sqlite+pysqlite:///{root/'reviews.db'}"); repo.create_schema_for_testing()
            api.REVIEW_PERSISTENCE = repo; api.API_RUN_ROOT = runs = root/"runs"; runs.mkdir(); api.verify_review_roughness = lambda *a, **kw: None
            source_dir = runs/"source"; (source_dir/"pages").mkdir(parents=True); (source_dir/"inputs").mkdir()
            from PIL import Image
            Image.new("RGB", (30,20), "white").save(source_dir/"pages"/"page_1.png")
            (source_dir/"inputs"/"original.png").write_bytes((source_dir/"pages"/"page_1.png").read_bytes())
            repo.create_review("source", source, owner=OWNER, artifact_dir=str(source_dir))
            repo.create_review("legacy", {"drawing_summary":{"drawing_name":"旧单"},"spring_parameters":{}}, owner=OWNER)
            # Transaction rollback after the first of two child inserts.
            repo.create_review("rollback", source, owner=OWNER)
            real_child = store.child_review; seen = []
            def fail_second(*args):
                seen.append(1)
                if len(seen) == 2: raise MultiSpecError("injected second-spec failure")
                return real_child(*args)
            rollback_ids = [v["variant_id"] for v in multi["variants"]][:2]
            with patch.object(store, "child_review", side_effect=fail_second):
                try: store.create_children(repo,"rollback",OWNER["user_id"],{"variant_ids":rollback_ids,"expected_source_revision":1,"idempotency_key":"rollback"},OWNER,runs)
                except MultiSpecError: pass
                else: raise AssertionError("Expected rollback")
            assert store.describe(repo,"rollback",OWNER["user_id"])["created_count"] == 0
            assert store.describe(repo,"rollback",OWNER["user_id"])["source_revision"] == 1
            repo.delete_review("rollback", owner_user_id=OWNER["user_id"])
            # Fifty independent specs with identical geometry remain fifty records.
            many_payload = fixture(50); many = source_review(many_payload,parse_multi_spec(many_payload))
            repo.create_review("many",many,owner=OWNER)
            many_result = store.create_children(repo,"many",OWNER["user_id"],{"variant_ids":[v["variant_id"] for v in many["multi_spec"]["variants"]],"expected_source_revision":1,"idempotency_key":"fifty"},OWNER,runs)
            assert len({v["job_id"] for v in many_result["reviews"]}) == 50
            store.delete_family(repo,"many",OWNER["user_id"],many_result["source_revision"])
            ids = [v["variant_id"] for v in multi["variants"]]
            body = {"variant_ids": ids[:2], "expected_source_revision": 1, "idempotency_key": "first"}
            with patch("ai_design_review.surface_terms._decide_with_llm", side_effect=AssertionError("No cloud calls")), TestClient(api.app) as client:
                assert client.get("/api/openapi.json").status_code == 200
                assert client.get("/api/reviews/source/variants").json()["created_count"] == 0
                assert client.patch("/api/reviews/source", json={"review":source,"expected_revision":1}).status_code == 409
                assert client.get("/api/reviews/source/generation-readiness").status_code == 409
                manifest = client.get("/api/reviews/source/variants").json()
                image_url = manifest["pages"][0]["image_url"]
                before_image = repo.get_review("source", owner_user_id=OWNER["user_id"])
                # Read-only sources must allow their owner's actual file bytes;
                # do not mistake the source editing restriction for ownership.
                with patch.object(api, "verify_review_roughness", side_effect=AssertionError("Source image reads must not normalize parameters")):
                    image_response = client.get(image_url)
                assert image_response.status_code == 200, image_response.text
                assert image_response.headers["content-type"] == "image/png"
                assert image_response.content == (source_dir/"pages"/"page_1.png").read_bytes()
                assert client.get("/api/reviews/source/artifacts/inputs/original.png").content == image_response.content
                assert repo.get_review("source", owner_user_id=OWNER["user_id"]) == before_image
                with patch.dict(os.environ, {"AI_REVIEW_MOCK_USER_ID": "another-user"}):
                    assert client.get(image_url).status_code == 404
                (runs/"secret.png").write_bytes(b"outside the source directory")
                assert client.get("/api/reviews/source/artifacts/%2e%2e%2f%2e%2e%2fsecret.png").status_code == 404
                assert client.get("/api/reviews/source/artifacts/pages/missing.png").status_code == 404
                assert client.patch("/api/reviews/source", json={"review":source,"expected_revision":1}).status_code == 409
                assert client.post("/api/reviews/source/standardize", json={"review":source}).status_code == 409
                assert client.get("/api/reviews/source/generation-package").status_code == 409
                response = client.post("/api/reviews/source/variants/create-reviews", json=body)
                assert response.status_code == 200, response.text
                result = response.json(); child_ids = [v["job_id"] for v in result["reviews"]]
                assert client.post("/api/reviews/source/variants/create-reviews", json=body).json()["reviews"][0]["job_id"] == child_ids[0]
                assert client.post("/api/reviews/source/variants/create-reviews", json={**body,"variant_ids":ids[1:]}).status_code == 409
                assert len(client.get("/api/reviews?root_only=true&limit=100").json()["reviews"]) == 2
                loaded = client.get(f"/api/reviews/{child_ids[0]}"); assert loaded.status_code == 200, loaded.text
                assert (runs/child_ids[0]/"pages"/"page_1.png").samefile(source_dir/"pages"/"page_1.png")
                sibling = repo.get_review(child_ids[1], owner_user_id=OWNER["user_id"])["review"]
                changed = loaded.json(); changed["drawing_summary"]["drawing_name"] = "独立改名"
                saved = client.patch(f"/api/reviews/{child_ids[0]}", json={"review":changed,"expected_revision":changed["review_revision"]})
                assert saved.status_code == 200, saved.text
                assert repo.get_review(child_ids[1], owner_user_id=OWNER["user_id"])["review"] == sibling
                confirmed = client.get(f"/api/reviews/{child_ids[0]}").json()
                for item in confirmed["spring_parameters"].values():
                    if isinstance(item,dict) and item.get("value") is not None:
                        item["need_human_review"] = False
                for point in confirmed["spring_parameters"].get("load_points", []): point["need_human_review"] = False
                confirmed["spring_parameters"].update(handedness=parameter("right",None,need_human_review=False),end_type=parameter("closed_and_ground",None,need_human_review=False),end_grinding=parameter("ground",None,need_human_review=False))
                confirm_response = client.patch(f"/api/reviews/{child_ids[0]}",json={"review":confirmed,"expected_revision":confirmed["review_revision"]})
                assert confirm_response.status_code == 200,confirm_response.text
                package_response = client.get(f"/api/reviews/{child_ids[0]}/generation-package")
                assert package_response.status_code == 200,package_response.text
                package = package_response.json()["parameter_package"]
                from ai_design_review.solidworks import build_solidworks_command
                frozen = deepcopy(package)
                command = build_solidworks_command("1000000123",package,confirmed)
                assert command["models"][0]["modelName"] == "独立改名"
                assert command["models"][0]["modelParameters"]["中径"] == 66
                assert "multi_spec_origin" not in str(command)
                confirmed["drawing_summary"]["drawing_name"] = "后续改名"
                assert frozen["source"]["drawing_name"] == "独立改名"
                assert client.delete("/api/reviews/source?expected_source_revision=1").status_code == 409
                assert client.delete(f"/api/reviews/{child_ids[0]}").status_code == 200
                assert (source_dir/"pages"/"page_1.png").exists()
                retry = client.post("/api/reviews/source/variants/create-reviews", json=body).json()
                assert retry["reviews"][0]["deleted"] is True
                value = client.get("/api/reviews/source/variants").json()
                rebuilt = client.post("/api/reviews/source/variants/create-reviews", json={**body,"expected_source_revision":value["source_revision"],"idempotency_key":"rebuild"})
                assert rebuilt.status_code == 200, rebuilt.text
                assert rebuilt.json()["reviews"][0]["job_id"] != child_ids[0]
                expect_error(lambda: store.describe(repo,"source","other-user"),404)
                value = store.describe(repo,"source",OWNER["user_id"])
                # Two simultaneous requests, same key and revision, create exactly one child.
                concurrent_body = {"variant_ids":[ids[2]],"expected_source_revision":value["source_revision"],"idempotency_key":"parallel"}
                with ThreadPoolExecutor(2) as pool:
                    values = list(pool.map(lambda _: store.create_children(repo,"source",OWNER["user_id"],concurrent_body,OWNER,runs),range(2)))
                assert values[0]["reviews"][0]["job_id"] == values[1]["reviews"][0]["job_id"]
                value = store.describe(repo,"source",OWNER["user_id"])
                deleted = client.delete(f'/api/reviews/source?expected_source_revision={value["source_revision"]}')
                assert deleted.status_code == 200, deleted.text
                assert len(deleted.json()["deleted_ids"]) == 4
                assert repo.get_review("legacy", owner_user_id=OWNER["user_id"])
                assert client.get("/api/reviews/source/variants").status_code == 404
    finally:
        api.REVIEW_PERSISTENCE, api.API_RUN_ROOT, api.verify_review_roughness = old_repo, old_root, old_verify
    migration_test()
    print("PASS multi-spec offline contracts, API, retry, concurrent creation, isolation, deletion, migration")


def migration_test():
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, text
    with tempfile.TemporaryDirectory() as d:
        url = f"sqlite+pysqlite:///{Path(d)/'migration.db'}"; old = os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"] = url
        try:
            cfg = Config("alembic.ini"); command.upgrade(cfg,"20260804_01")
            # Legacy PostgreSQL sequence migration does not alter review columns.
            command.stamp(cfg,"20260911_01")
            engine = create_engine(url)
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO drawing_reviews (job_id,revision,review_snapshot,event_sequence,created_at,updated_at) VALUES ('old',1,'{}',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            command.upgrade(cfg,"head")
            with engine.connect() as conn:
                row = conn.execute(text("SELECT record_kind,parent_review_id,variant_id FROM drawing_reviews WHERE job_id='old'")).one()
                assert tuple(row) == ("single",None,None)
            command.downgrade(cfg,"20260911_01"); engine.dispose()
        finally:
            if old is None: os.environ.pop("DATABASE_URL",None)
            else: os.environ["DATABASE_URL"] = old


if __name__ == "__main__": main()
