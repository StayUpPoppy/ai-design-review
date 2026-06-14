from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


CAD_EXTENSIONS = {".dwg", ".dxf", ".step", ".stp", ".iges", ".igs"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def probe_file(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path)
    suffix = path.suffix.lower()
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "extension": suffix,
        "size_bytes": path.stat().st_size if path.exists() else None,
        "kind": "unknown",
        "pdf_text_chars": None,
        "has_text_layer": None,
        "is_scanned_like": None,
    }

    if suffix == ".pdf":
        result["kind"] = "pdf"
        chars = _extract_pdf_text_chars(path)
        result["pdf_text_chars"] = chars
        result["has_text_layer"] = chars > 0
        result["is_scanned_like"] = chars == 0
    elif suffix in CAD_EXTENSIONS:
        result["kind"] = "cad"
        result["is_scanned_like"] = False
    elif suffix in IMAGE_EXTENSIONS:
        result["kind"] = "image"
        result["is_scanned_like"] = True

    return result


def render_pdf_with_pdftoppm(
    pdf_path: str | Path,
    output_dir: str | Path,
    prefix: str = "page",
    dpi: int = 200,
) -> list[str]:
    """Render a PDF with Poppler's pdftoppm if available."""
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is not available on PATH.")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    output_prefix = output / prefix
    command = [
        pdftoppm,
        "-png",
        "-r",
        str(dpi),
        str(pdf_path),
        str(output_prefix),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return [str(p) for p in sorted(output.glob(f"{prefix}-*.png"))]


def _extract_pdf_text_chars(path: Path) -> int:
    try:
        from pypdf import PdfReader
    except Exception:
        return 0

    try:
        reader = PdfReader(str(path))
        return sum(len(page.extract_text() or "") for page in reader.pages)
    except Exception:
        return 0

