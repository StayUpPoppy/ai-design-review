"""Inspect the browser-generated A4 fixtures, including every continuation page.

Run after test_parameter_confirmation_sheet_browser.mjs with the bundled Python
(pypdf/Pillow) and pdftoppm. No production data or remote services are used.
"""
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw
from pypdf import PdfReader
from pypdf.generic import ContentStream


def pixels(image: Image.Image):
    return (image.getpixel((x, y)) for y in range(image.height) for x in range(image.width))


def check(path: Path) -> list[Image.Image]:
    reader = PdfReader(path)
    assert len(reader.pages) > 1, "Fixture must exercise real pagination"
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        assert text.count("弹簧参数确认单") == 1, (path.name, index, "missing/duplicate title")
        assert len(text.replace("弹簧参数确认单", "").strip()) > 20, (path.name, index, "empty page")
        assert abs(float(page.mediabox.width) - 595.28) < 1
        assert abs(float(page.mediabox.height) - 841.89) < 1
        draws = [args[0] for args, op in ContentStream(page.get_contents(), reader).operations if op == b"Do"]
        objects = page["/Resources"].get("/XObject", {})
        assert any(objects[name].get_object().get("/Subtype") == "/Image" for name in draws), (path.name, index, "missing logo draw")
    subprocess.run(["pdftoppm", "-r", "72", "-png", str(path), str(path.with_suffix(""))], check=True)
    mm = 72 / 25.4
    headers = []
    for index in range(1, len(reader.pages) + 1):
        # pdftoppm pads page numbers to the total page count's digit width.
        name = f"{path.stem}-{index:0{len(str(len(reader.pages)))}d}.png"
        with Image.open(path.parent / name) as source:
            image = source.convert("RGB")
        logo = image.crop(tuple(round(v * mm) for v in (14, 14, 52, 28)))
        blue = sum(b > r + 25 and g > r + 10 for r, g, b in pixels(logo))
        assert blue > 100, (path.name, index, "logo missing, cropped or misplaced")
        dark = sum(value < 180 for value in pixels(logo.convert("L")))
        assert dark > 100, (path.name, index, "monochrome logo illegible")
        gap = image.crop(tuple(round(v * mm) for v in (14, 29, 196, 31)))
        assert sum(min(pixel) < 220 for pixel in pixels(gap)) < 5, (path.name, index, "header overlaps body")
        headers.append(image.crop((0, 0, image.width, round(44 * mm))))
        if index == 1:
            image.convert("L").save(path.parent / f"{path.stem}-monochrome.png")
    print(f"{path.name}: {len(reader.pages)} A4 pages, every title/logo/clearance verified (including final signature page)")
    return headers


if __name__ == "__main__":
    files = [Path(value) for value in sys.argv[1:]] or [
        Path("outputs/confirmation-sheet-qa/confirmation-sheet.pdf"),
        Path("outputs/confirmation-sheet-qa/confirmation-sheet-no-background.pdf"),
    ]
    for index, path in enumerate(files):
        headers = check(path)
        if index == 0:
            width, height = headers[0].size
            montage = Image.new("RGB", (width * 2, (height + 20) * ((len(headers) + 1) // 2)), "#e9edf3")
            draw = ImageDraw.Draw(montage)
            for number, header in enumerate(headers):
                x, y = number % 2 * width, number // 2 * (height + 20)
                draw.text((x + 12, y + 3), f"Page {number + 1}", fill="#172033")
                montage.paste(header, (x, y + 20))
            montage.save(path.parent / "branding-pages.png")
