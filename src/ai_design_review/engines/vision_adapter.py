from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RecognitionEngine


class VisionEngine(RecognitionEngine):
    """Adapter placeholder for OpenAI Vision + Structured Outputs."""

    name = "vision"

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "VisionEngine is a production adapter placeholder. "
            "Use a vision model to map OCR/dimension evidence to spring-specific fields."
        )

