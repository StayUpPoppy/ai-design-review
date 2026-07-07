from __future__ import annotations

import shutil
import subprocess
import sys
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
        "pdf_text": None,
        "has_text_layer": None,
        "is_scanned_like": None,
    }

    if suffix == ".pdf":
        result["kind"] = "pdf"
        pdf_text = extract_pdf_text(path)
        chars = len(pdf_text)
        result["pdf_text_chars"] = chars
        result["pdf_text"] = pdf_text[:12000]
        result["has_text_layer"] = chars > 0
        result["is_scanned_like"] = chars == 0
    elif suffix in CAD_EXTENSIONS:
        result["kind"] = "cad"
        result["is_scanned_like"] = False
    elif suffix in IMAGE_EXTENSIONS:
        result["kind"] = "image"
        result["is_scanned_like"] = True

    return result


def extract_pdf_text(path: str | Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def render_pdf_with_pdftoppm(
    pdf_path: str | Path,
    output_dir: str | Path,
    prefix: str = "page",
    dpi: int = 200,
) -> list[str]:
    """Render a PDF with Poppler's pdftoppm if available."""
    candidates = _pdftoppm_candidates()
    if not candidates:
        raise RuntimeError("pdftoppm is not available on PATH.")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    output_prefix = output / prefix
    errors: list[str] = []
    for pdftoppm in candidates:
        for stale in output.glob(f"{prefix}-*.png"):
            try:
                stale.unlink()
            except OSError:
                pass
        command = [
            pdftoppm,
            "-png",
            "-r",
            str(dpi),
            str(pdf_path),
            str(output_prefix),
        ]
        completed = subprocess.run(command, capture_output=True)
        rendered = [str(p) for p in sorted(output.glob(f"{prefix}-*.png"))]
        if completed.returncode == 0 and rendered:
            return rendered
        stderr = completed.stderr.decode(errors="replace") if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
        stdout = completed.stdout.decode(errors="replace") if isinstance(completed.stdout, bytes) else str(completed.stdout or "")
        detail = (stderr or stdout or "no output").strip()
        errors.append(f"{pdftoppm}: exit {completed.returncode}; {detail}")
    raise RuntimeError("pdftoppm failed to render PDF. Tried: " + " | ".join(errors))


def _pdftoppm_candidates() -> list[str]:
    found: list[str] = []
    first = shutil.which("pdftoppm")
    if first:
        found.append(first)
    if sys.platform.startswith("win"):
        try:
            completed = subprocess.run(["where.exe", "pdftoppm"], capture_output=True, text=True, check=False)
            if completed.returncode == 0:
                found.extend(line.strip() for line in completed.stdout.splitlines() if line.strip())
        except OSError:
            pass

    unique: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return sorted(unique, key=_pdftoppm_priority)


def _pdftoppm_priority(path: str) -> tuple[int, str]:
    suffix = Path(path).suffix.lower()
    if suffix == ".exe":
        return (0, path.lower())
    return (1, path.lower())


def _extract_pdf_text_chars(path: Path) -> int:
    return len(extract_pdf_text(path))
