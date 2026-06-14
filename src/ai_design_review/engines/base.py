from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class RecognitionEngine(ABC):
    name: str

    @abstractmethod
    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Return normalized candidate dictionaries."""

