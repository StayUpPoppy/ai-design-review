"""Read the supplied company XLSX without modifying it; emit a versioned directory."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET


def read_catalog(path: Path) -> dict:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        strings = ["".join(item.itertext()) for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", ns)] if "xl/sharedStrings.xml" in archive.namelist() else []
        rows = []
        for row in ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall("m:sheetData/m:row", ns):
            values = {}
            for cell in row.findall("m:c", ns):
                value = cell.find("m:v", ns)
                inline = cell.find("m:is", ns)
                text = value.text if value is not None else "".join(inline.itertext()) if inline is not None else ""
                if cell.get("t") == "s" and text: text = strings[int(text)]
                if text: values[cell.get("r").rstrip("0123456789")] = str(text).strip()
            if values: rows.append(values)
    if rows[0] != {"A": "类别", "B": "名称"}:
        raise ValueError("请使用只有类别、名称两列的无备注版目录")
    names = [r["B"] for r in rows[1:] if r.get("A") == "表面处理" and r.get("B")]
    if len(names) != 49 or len(set(names)) != 49: raise ValueError("目录应包含49个不同名称")
    return {"version": "company-surface-treatments-v1-20261023", "source": path.name,
            "items": [{"id": "sfc_" + hashlib.sha256(name.encode()).hexdigest()[:12], "name": name} for name in names]}


if __name__ == "__main__":
    catalog = read_catalog(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
