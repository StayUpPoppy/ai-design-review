from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.qwen_vision_adapter import (  # noqa: E402
    QWEN_SYSTEM_PROMPT,
    QwenVisionEngine,
    parse_qwen_json,
    qwen_payload_to_candidates,
    qwen_runtime_status,
)
from ai_design_review.io_utils import read_json
from ai_design_review.workflow import DrawingReviewWorkflow


def main() -> None:
    _assert_thinking_configuration()
    _assert_thinking_request_and_retry()
    assert "Ra 12.5" in QWEN_SYSTEM_PROMPT
    assert "H1/H2 只属于 load_points" in QWEN_SYSTEM_PROMPT
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
            "working_angle": {"value": 35, "unit": "deg", "confidence": 0.8, "evidence": "35°"},
            "bend_radius": {"value": 3.5, "unit": "mm", "confidence": 0.78, "evidence": "R3.5"},
            "leg1_length": {"value": 20, "unit": "mm", "confidence": 0.78, "evidence": "20"}
          },
          "spring_features": {
            "spring_family": {"value": "helical", "confidence": 0.8, "evidence": "螺旋结构"},
            "spring_shape": {"value": "cylindrical", "confidence": 0.7, "evidence": "圆柱结构"},
            "manufacturing_method": {"value": "cold_coiled", "confidence": 0.82, "evidence": "GB/T 1239.2"},
            "wire_section": {"value": "round", "confidence": 0.76, "evidence": "圆线"},
            "pitch_type": {"value": "constant", "confidence": 0.68, "evidence": "等节距"}
          },
          "standard_selection_inference": {
            "selected_standard": "GB/T 1239.2-2009",
            "manufacturing_method": "cold_coiled",
            "confidence": 0.82,
            "evidence": ["GB/T 1239.2"],
            "reason": "标准号指向冷卷",
            "need_human_review": false
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
    assert fields["bend_radius"]["value"] == 3.5
    assert fields["leg1_length"]["value"] == 20
    assert fields["manufacturing_method"]["value"] == "cold_coiled"
    assert fields["spring_shape"]["value"] == "cylindrical"
    assert fields["standard_selection_inference"]["value"]["selected_standard"] == "GB/T 1239.2-2009"

    end_candidates = qwen_payload_to_candidates(
        {
            "parameters": {
                "end_grinding": {"value": "两端磨平", "evidence": "两端磨平"},
                "end_type": {"value": "闭口", "evidence": "端部闭口"},
            }
        }
    )
    end_fields = {item["field"]: item for item in end_candidates}
    assert end_fields["end_grinding"]["value"] == "两端磨削"
    assert end_fields["end_type"]["value"] == "两端并紧"

    rules = read_json("config/factory_rules.json")
    review = DrawingReviewWorkflow(rules).run(None, candidates)
    assert review["drawing_summary"]["spring_type"] == "torsion_spring"
    assert review["spring_parameters"]["wire_diameter"]["value"] == 2
    assert review["spring_parameters"]["bend_radius"]["value"] == 3.5
    assert any(item["key"] == "bend_radius" and item["label"] == "折弯半径" for item in review["spring_template"]["fields"])
    surface = next(item for item in review["technical_requirements"] if item["type"] == "surface")
    assert surface["content"] == "电镀-镀彩锌"
    assert surface["raw_content"] == "镀锌五彩"
    assert surface["standard_content"] == "电镀-镀彩锌"
    assert surface["normalization_status"] == "alias_matched"
    print("qwen vision adapter test passed")


def _assert_thinking_configuration() -> None:
    with patch.dict(os.environ, {}, clear=True):
        engine = QwenVisionEngine(api_key="test-key")
        assert engine.enable_thinking is False
        assert engine.thinking_config_status == "default"
        runtime = qwen_runtime_status()
        assert runtime["thinking_enabled"] is False
        assert runtime["thinking_config_status"] == "default"

    with patch.dict(os.environ, {"QWEN_VISION_ENABLE_THINKING": "true"}, clear=True):
        engine = QwenVisionEngine(api_key="test-key")
        assert engine.enable_thinking is True
        assert engine.thinking_config_status == "configured"

    with patch.dict(os.environ, {"QWEN_VISION_ENABLE_THINKING": "unexpected"}, clear=True):
        engine = QwenVisionEngine(api_key="test-key")
        assert engine.enable_thinking is False
        assert engine.thinking_config_status == "invalid_defaulted_to_false"
        runtime = qwen_runtime_status()
        assert runtime["thinking_enabled"] is False
        assert runtime["thinking_config_status"] == "invalid_defaulted_to_false"


def _assert_thinking_request_and_retry() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "drawing.png"
        image_path.write_bytes(b"fake-image")

        normal_client = _FakeClient([_FakeResponse(200)])
        with patch("httpx.Client", return_value=normal_client):
            engine = QwenVisionEngine(api_key="test-key", enable_thinking=False)
            engine._call_qwen([image_path])
        assert len(normal_client.calls) == 1
        assert normal_client.calls[0]["json"]["enable_thinking"] is False

        thinking_client = _FakeClient([_FakeResponse(200)])
        with patch("httpx.Client", return_value=thinking_client):
            engine = QwenVisionEngine(api_key="test-key", enable_thinking=True)
            engine._call_qwen([image_path])
        assert thinking_client.calls[0]["json"]["enable_thinking"] is True

        retry_client = _FakeClient([
            _FakeResponse(400, text="response_format is not supported"),
            _FakeResponse(200),
        ])
        with patch("httpx.Client", return_value=retry_client):
            engine = QwenVisionEngine(api_key="test-key", enable_thinking=False)
            engine._call_qwen([image_path])
        assert len(retry_client.calls) == 2
        assert retry_client.calls[0]["json"]["enable_thinking"] is False
        assert retry_client.calls[1]["json"]["enable_thinking"] is False
        assert "response_format" in retry_client.calls[0]["json"]
        assert "response_format" not in retry_client.calls[1]["json"]


class _FakeResponse:
    def __init__(self, status_code: int, *, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "{}"}}]}


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, endpoint: str, *, headers: dict, json: dict) -> _FakeResponse:
        self.calls.append({"endpoint": endpoint, "headers": dict(headers), "json": dict(json)})
        return self.responses.pop(0)


if __name__ == "__main__":
    main()
