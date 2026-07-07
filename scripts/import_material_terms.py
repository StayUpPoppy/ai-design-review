from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg_rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import material standard terms from Excel.")
    parser.add_argument("--xlsx", required=True, help="Path to 材质标准表.xlsx")
    parser.add_argument("--output", default="config/material_terms.json", help="Output JSON path")
    parser.add_argument("--sheet", default="Sheet1", help="Worksheet containing the standard materials")
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    output_path = Path(args.output)
    terms = read_material_terms_from_xlsx(xlsx_path, args.sheet)
    payload = {
        "version": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": xlsx_path.name,
        "source_sheet": args.sheet,
        "terms": terms,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Imported {len(terms)} material terms to {output_path}")


def read_material_terms_from_xlsx(xlsx_path: Path, sheet_name: str) -> list[str]:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    with zipfile.ZipFile(xlsx_path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_path = _sheet_xml_path(archive, sheet_name)
        rows = _read_sheet_rows(archive, sheet_path, shared_strings)

    if not rows:
        raise ValueError(f"Worksheet is empty: {sheet_name}")
    headers = [str(cell).strip() for cell in rows[0]]
    try:
        name_index = headers.index("名称")
    except ValueError as exc:
        raise ValueError(f"Worksheet {sheet_name} must contain header: 名称") from exc

    terms: list[str] = []
    seen: set[str] = set()
    for row in rows[1:]:
        name = _cell(row, name_index)
        if not name or name in seen:
            continue
        terms.append(name)
        seen.add(name)
    if not terms:
        raise ValueError(f"No material terms found in worksheet: {sheet_name}")
    return terms


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root.findall("main:si", NS):
        parts = [node.text or "" for node in item.findall(".//main:t", NS)]
        values.append("".join(parts))
    return values


def _sheet_xml_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pkg_rel:Relationship", NS)
    }
    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        if sheet.attrib.get("name") != sheet_name:
            continue
        relationship_id = sheet.attrib[f"{{{NS['rel']}}}id"]
        target = rel_targets[relationship_id]
        return _normalize_excel_target(target)
    available = [sheet.attrib.get("name", "") for sheet in workbook.findall("main:sheets/main:sheet", NS)]
    raise ValueError(f"Worksheet {sheet_name} not found. Available sheets: {available}")


def _normalize_excel_target(target: str) -> str:
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def _read_sheet_rows(archive: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: list[list[str]] = []
    for row_node in root.findall(".//main:sheetData/main:row", NS):
        row_values: dict[int, str] = {}
        for cell in row_node.findall("main:c", NS):
            ref = cell.attrib.get("r", "")
            column_index = _column_index(ref)
            row_values[column_index] = _cell_value(cell, shared_strings)
        if row_values:
            rows.append([row_values.get(index, "") for index in range(max(row_values) + 1)])
    return rows


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", NS)).strip()
    value_node = cell.find("main:v", NS)
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        return shared_strings[int(value)].strip()
    return value.strip()


def _column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return max(0, index - 1)


def _cell(row: list[Any], index: int) -> str:
    if index >= len(row):
        return ""
    return str(row[index] or "").strip()


if __name__ == "__main__":
    main()
