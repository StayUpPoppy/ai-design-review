"""Field-aware coil aliases. A per-end unit is never a total-coil unit."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def coil_unit_supported(field: str, unit: Any) -> bool:
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(unit or "turns"))).lower()
    common = {"turns", "turn", "coil", "coils", "圈"}
    per_end = {f"{base}{suffix}" for base in common for suffix in ("/end", "/eachend", "/端", "/单端")}
    return text in common or field == "support_coils" and text in per_end
