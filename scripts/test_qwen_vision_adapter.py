from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.qwen_vision_adapter import parse_qwen_json, qwen_payload_to_candidates
from ai_design_review.io_utils import read_json
from ai_design_review.workflow import DrawingReviewWorkflow


def main() -> None:
    payload = parse_qwen_json(
        """
        ```json
        {
          "spring_type": {"value": "torsion_spring", "label": "扭转弹簧", "confidence": 0.91, "evidence": "图中存在角度和双臂结构"},
          "drawing_summary": {"drawing_name": "UQD04阳接头弹簧", "drawing_no": "3624CA-74", "version": ""},
          "parameters": {
            "material": {"value": "65Mn", "confidence": 0.88, "evidence": "材质 65Mn"},
            "wire_diameter": {"value": 2, "unit": "mm", "confidence": 0.92, "evidence": "线径 φ2"},
            "total_coils": {"value": 6, "unit": "turns", "confidence": 0.86, "evidence": "总圈数 6"},
            "pitch": {"value": 2.7, "unit": "mm", "confidence": 0.82, "evidence": "节距 2.7"},
            "working_angle": {"value": 35, "unit": "deg", "confidence": 0.8, "evidence": "35°"}
          },
          "technical_requirements": [
            {"type": "surface", "content": "镀锌五彩", "confidence": 0.9, "evidence": "表面处理 镀锌五彩"},
            {"type": "hardness", "content": "HRC30-35", "confidence": 0.86, "evidence": "硬度 HRC30-35"}
          ],
          "notes": "只输出识别到的尺寸"
        }
        ```
        """
    )
    candidates = qwen_payload_to_candidates(payload)
    fields = {item["field"]: item for item in candidates}
    assert fields["wire_diameter"]["value"] == 2
    assert fields["surface_requirement"]["value"] == "镀锌五彩"
    assert fields["hardness"]["value"] == "HRC30-35"
    assert fields["spring_type"]["value"] == "扭转弹簧"

    rules = read_json("config/factory_rules.json")
    review = DrawingReviewWorkflow(rules).run(None, candidates)
    assert review["drawing_summary"]["spring_type"] == "torsion_spring"
    assert review["spring_parameters"]["wire_diameter"]["value"] == 2
    assert any(item["type"] == "surface" and item["content"] == "镀锌五彩" for item in review["technical_requirements"])
    print("qwen vision adapter test passed")


if __name__ == "__main__":
    main()
