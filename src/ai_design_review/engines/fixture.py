from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RecognitionEngine
from ..io_utils import read_json


class FixtureEngine(RecognitionEngine):
    name = "fixture"

    def __init__(self, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        payload = read_json(self.fixture_path)
        return payload.get("candidates", payload)

