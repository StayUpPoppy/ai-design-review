"""Conservative dimension text normalization shared by extraction and navigation.

Only an entire run of single glyphs is joined. Labels, separate numbers,
tolerance columns and dimension identifiers are never stripped to make a value.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

NUMBER = r"[-+]?\d+(?:\.\d+)?"
DIAMETER = "φΦϕøØ⌀"


def dimension_text(text: Any) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).strip().rstrip("。;；")
    match = re.fullmatch(r"([φΦϕøØ⌀]|Ra)?\s*([-+]?\s*[\d.](?:\s+[\d.])+)(\s*(?:mm|μm|µm|圈))?", text, re.I)
    if match:
        run = re.sub(r"\s+", "", match[2])
        if re.fullmatch(NUMBER, run) and ("." in run or match[1]):
            return (match[1] or "") + run + (match[3] or "")
    return text


def dimension_number(text: Any) -> float | None:
    match = re.fullmatch(rf"(?:[{DIAMETER}]|Ra)?\s*({NUMBER})\s*(?:mm|μm|µm|圈)?", dimension_text(text), re.I)
    return float(match[1]) if match else None


def numeric_identity(text: Any) -> str:
    return re.sub(r"\s+", "", dimension_text(text)).casefold()


def safe_glyph_run(tokens: list[dict[str, Any]]) -> bool:
    """PDF glyphs must follow one baseline, with no cell-sized gaps or turns."""
    if len(tokens) < 2:
        return True
    boxes = [t["position"] for t in tokens]
    centers = [(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2) for b in boxes]
    axis = 0 if max(c[0] for c in centers) - min(c[0] for c in centers) >= max(c[1] for c in centers) - min(c[1] for c in centers) else 1
    size, cross = ("width", "height") if axis == 0 else ("height", "width")
    deltas = [b[axis] - a[axis] for a, b in zip(centers, centers[1:])]
    if any(d > 0 for d in deltas) and any(d < 0 for d in deltas):
        return False
    for i, delta in enumerate(deltas):
        if abs(delta) - (boxes[i][size] + boxes[i + 1][size]) / 2 > max(b[size] for b in boxes) * 1.6:
            return False
        if abs(centers[i][1 - axis] - centers[i + 1][1 - axis]) > max(b[cross] for b in boxes) * .65:
            return False
    return True
