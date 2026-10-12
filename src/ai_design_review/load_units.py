"""Read load conditions in base units without changing their stored values."""
from __future__ import annotations

import math
from typing import Any

from .standardizers.calculation_state import LENGTH_UNITS

FORCE_UNITS = {"n": 1, "牛": 1, "kn": 1000, "kgf": 9.80665}


def in_base_units(value: Any, unit: Any, *, force: bool = False) -> float | None:
    if isinstance(value, bool):
        return None
    factor = (FORCE_UNITS if force else LENGTH_UNITS).get(str(unit or ("N" if force else "mm")).strip().lower())
    try:
        number = float(value) * factor if factor is not None and value not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number is not None and math.isfinite(number) else None


def normalized_load_point(point: dict[str, Any]) -> dict[str, Any]:
    return {**point, "height": in_base_units(point.get("height"), point.get("height_unit")),
            "force": in_base_units(point.get("force"), point.get("force_unit"), force=True)}
