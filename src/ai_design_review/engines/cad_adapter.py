from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RecognitionEngine


class CadEngine(RecognitionEngine):
    """Adapter placeholder for DXF/DWG parsing.

    DXF can be handled with ezdxf. DWG normally needs ODA SDK, AutoCAD
    automation, Autodesk Platform Services, or a conversion step.
    """

    name = "cad"

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "CadEngine is a production adapter placeholder. "
            "Map DIMENSION/TEXT/MTEXT/LEADER entities to normalized candidates."
        )

