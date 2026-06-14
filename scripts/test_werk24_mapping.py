from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.engines.werk24_adapter import messages_to_candidate_payload


def main() -> None:
    messages = [
        {
            "request_id": "test",
            "message_type": "ASK",
            "message_subtype": "BALLOONS",
            "page_number": 1,
            "is_successful": True,
            "exceptions": [],
            "payload_dict": {
                "ask_type": "BALLOONS",
                "balloons": [{"reference_id": 101, "center": [300, 400]}],
            },
        },
        {
            "request_id": "test",
            "message_type": "ASK",
            "message_subtype": "FEATURES",
            "page_number": 1,
            "is_successful": True,
            "exceptions": [],
            "payload_dict": {
                "ask_type": "FEATURES",
                "dimensions": [
                    {
                        "reference_id": 101,
                        "label": "25 0/-0.02",
                        "confidence": {"score": 0.91},
                        "quantity": 1,
                        "size": {
                            "value": 25,
                            "unit": "mm",
                            "size_type": "DIAMETER",
                            "tolerance": {
                                "deviation_upper": 0,
                                "deviation_lower": -0.02,
                                "tolerance_grade": None,
                            },
                        },
                    }
                ],
            },
        },
        {
            "request_id": "test",
            "message_type": "ASK",
            "message_subtype": "META_DATA",
            "page_number": 1,
            "is_successful": True,
            "exceptions": [],
            "payload_dict": {
                "ask_type": "META_DATA",
                "designation": [{"reference_id": 201, "value": "UQD06外弹簧"}],
                "identifiers": [
                    {
                        "reference_id": 202,
                        "value": "YD4765020175",
                        "identifier_type": "DRAWING_ID",
                    }
                ],
                "material_options": [
                    {
                        "reference_id": 203,
                        "material_combination": [
                            {
                                "raw_ocr": "SUS304",
                                "standard": None,
                                "designation": "SUS304",
                            }
                        ],
                    }
                ],
            },
        },
    ]

    payload = messages_to_candidate_payload(messages)
    candidates = payload["candidates"]

    assert len(candidates) == 4
    dimension = next(item for item in candidates if item["feature_type"] == "dimension")
    assert dimension["value"] == 25
    assert dimension["tolerance_lower"] == -0.02
    assert dimension["position"]["x"] == 300
    assert any(item["field"] == "drawing_name" for item in candidates)
    assert any(item["field"] == "drawing_no" for item in candidates)
    assert any(item["field"] == "material" and item["value"] == "SUS304" for item in candidates)
    print("werk24 mapping test passed")


if __name__ == "__main__":
    main()
