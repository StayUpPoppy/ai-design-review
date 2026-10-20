"""No cloud calls: evidence filtering, source merging and old-review protection."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.surface_roughness import roughness_evidence_assessment, ensure_surface_roughness_parameter, verify_roughness_candidates
from ai_design_review.engines.qwen_vision_adapter import qwen_payload_to_candidates
from ai_design_review.fusion import fuse_candidates
from ai_design_review.generation_readiness import build_generation_parameter_package
from test_solidworks_export import base_review


def fields(payload, blocks=None):
    candidates = qwen_payload_to_candidates({"spring_type": "compression_spring", **payload})
    if blocks is not None:
        candidates = [c for c in candidates if c.get("field") != "surface_roughness_ra"] + verify_roughness_candidates(
            [c for c in candidates if c.get("field") == "surface_roughness_ra"], blocks, "fixture-document")
    return fuse_candidates(candidates)["fields"]


def block(text, page=1, x=.1):
    return {"text": text, "source": "local_ocr", "page": page, "position": {"x": x, "y": .1, "width": .1, "height": .02}}


def run():
    fixtures = json.loads((Path(__file__).parent / "fixtures/roughness_evidence.json").read_text(encoding="utf-8"))
    for row in fixtures:
        status, reason = roughness_evidence_assessment(row["value"], row["text"], structured=row.get("structured", False))
        assert status == row["status"] and reason, (row, status)
    for text in ["可能Ra6.3", "未标注Ra12.5", "项目常规参考Ra12.5", "例如Ra12.5或Ra6.3"]:
        assert "surface_roughness_ra" not in fields({"notes": text}), text
    discussion = "示意图两端面标有表面粗糙度符号，Ra12.5或Ra6.3。我们再看，need_human_review=true，surface_roughness_ra应保留核对。"
    result = fields({"notes": discussion})["surface_roughness_ra"]
    assert result["value"] is None and result["need_human_review"]
    assert all(item["evidence_status"] == "unverified" for item in result["roughness_candidates"])
    assert all(item["evidence"] == discussion for item in result["roughness_candidates"])
    result = fields({"parameters": {"surface_roughness_ra": {"value": 6.3, "evidence": "无法辨认符号"}}})["surface_roughness_ra"]
    assert result["value"] is None and result["roughness_candidates"][0]["evidence_status"] == "unverified"
    direct = {"value": 12.5, "evidence": "两端面 Ra12.5", "surface_location": "两端面", "page": 2}
    result = fields({"parameters": {"surface_roughness_ra": direct}, "notes": discussion}, [block("两端面Ra12.5", 2)])["surface_roughness_ra"]
    assert result["value"] == 12.5 and result["surface_location"] == "两端面"
    assert any(item["value"] == 6.3 and item["evidence_status"] == "unverified" for item in result["roughness_candidates"])
    assert any(record["page"] == 2 for item in result["roughness_candidates"] for record in item["evidence_records"])
    for right in (12.5, 6.3):
        text = f"左端面Ra12.5，右端面Ra{right}"
        result = fields({"notes": text}, [block("左端面Ra12.5"), block(f"右端面Ra{right}", x=.7)])["surface_roughness_ra"]
        assert result["value"] is None and result["roughness_conflict"] if right != 12.5 else result["value"] == 12.5 and not result.get("roughness_conflict")
        assert {item["location"] for item in result["roughness_candidates"]} == {"左端面", "右端面"}
    result = fields({"notes": "外圆Ra12.5；两端面Ra12.5"}, [block("外圆Ra12.5"), block("两端面Ra12.5", x=.7)])["surface_roughness_ra"]
    assert len(result["roughness_candidates"]) == 2, "Different scopes cannot merge just because Ra is equal"
    assert result["roughness_conflict"]
    # Existing review values and confirmations remain byte-for-byte unchanged.
    review = base_review()
    review["spring_parameters"]["surface_roughness_ra"] = {
        "value": 6.3, "unit": "μm", "source": ["human_edited"], "need_human_review": False,
        "evidence": discussion, "roughness_candidates": [{"value": 12.5, "evidence": discussion}, {"value": 6.3, "evidence": discussion}],
        "confirmation_snapshot": {"value": 6.3}}
    before = deepcopy(review["spring_parameters"]["surface_roughness_ra"])
    ensure_surface_roughness_parameter(review)
    assert review["spring_parameters"]["surface_roughness_ra"] == before
    preview = build_generation_parameter_package(review)["solidworks_preview"]
    assert preview["titleBlockProperties"]["表面粗糙度"] == 6.3
    assert "evidence_status" not in json.dumps(preview)
    print(f"PASS: {len(fixtures)} shared evidence fixtures, commentary exclusion, unverified candidates, locations, sources and old-review protection")


if __name__ == "__main__":
    run()
