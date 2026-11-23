"""Fixed SVG drawing data, layout and vector PDF rendering, independent of SW."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree as ET

from .generation_readiness import assess_generation_readiness, build_generation_parameter_package
from .generation_contract import handedness_label
from .engineering_units import metric_review
from .solidworks import build_solidworks_technical_projection, _confirmed_optional_mm, _solid_label
from .surface_roughness import confirmed_surface_roughness
from .material_catalog import material_catalog_display_value
from .standardizers.design_checks import calculate_design_checks
from .standardizers.calculation_state import parameter_current

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


class TemplatePdfError(ValueError):
    def __init__(self, code: str, message: str, *, field: str = "template", issues: list | None = None):
        super().__init__(message)
        self.code, self.field, self.issues = code, field, issues or []

    def detail(self):
        return {"code": self.code, "message": str(self), "issues": self.issues or [{"field": self.field, "reason": str(self)}]}


def resource_root() -> Path:
    return Path(os.getenv("PDF_TEMPLATE_ROOT") or Path(__file__).resolve().parents[2] / ".local-assets/template-pdf/35-9").resolve()


def resources() -> "Resources":
    root = resource_root()
    files = [root / name for name in ("template.svg", "fields.json", "fonts/primary.ttf", "fonts/fallback.ttf")]
    try:
        if not all(path.is_file() for path in files):
            raise TemplatePdfError("template_pdf_resources_missing", "模板 PDF 资源未配置，请配置模板与字体目录。")
        signature = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files)
    except OSError as exc:
        raise TemplatePdfError("template_pdf_resources_unreadable", "模板 PDF 资源无法读取，请检查资源目录权限。") from exc
    return _load_resources(signature)


@lru_cache(maxsize=4)
def _load_resources(signature) -> "Resources":
    try:
        return Resources([Path(item[0]) for item in signature])
    except TemplatePdfError:
        raise
    except Exception as exc:
        raise TemplatePdfError("template_pdf_resources_invalid", "模板或字体资源无法读取，请检查资源包。") from exc


def resource_status() -> dict[str, Any]:
    try:
        item = resources()
        return {"available": True, "template_id": "35-9", "template_version": item.version}
    except TemplatePdfError as exc:
        return {"available": False, **exc.detail()}


class Resources:
    def __init__(self, paths):
        from fontTools.ttLib import TTFont
        self.svg = paths[0].read_bytes()
        self.manifest = json.loads(paths[1].read_text(encoding="utf-8"))
        self.fields = self.manifest["templates"][0]["fields"]
        self.keys = {item["key"] for item in self.fields}
        root = ET.fromstring(self.svg)
        if root.get("viewBox") != "0 0 210 297":
            raise ValueError("A4 template expected")
        group = root.find(f"{{{NS}}}g[@id='dynamic-fields']")
        if group is None:
            raise ValueError("Missing dynamic field group")
        nodes = {e.get("id") for e in group if e.get("data-field")}
        if len(nodes) != len(self.fields) or nodes != {f["id"] for f in self.fields}:
            raise ValueError("Field manifest and SVG do not match")
        self.fonts = []
        for path in paths[2:]:
            font = TTFont(path, fontNumber=0)
            self.fonts.append((font.getBestCmap(), font.getGlyphSet(), font["hmtx"].metrics, font["head"].unitsPerEm))
        self.version = sha256(b"".join(path.read_bytes() for path in paths)).hexdigest()

    def glyph(self, character):
        for cmap, glyphs, metrics, units in self.fonts:
            name = cmap.get(ord(character))
            if name is not None:
                return glyphs[name], metrics[name][0], units, glyphs
        raise TemplatePdfError("template_pdf_missing_glyph", f"图纸字体不支持字符“{character}”，请修改对应文字。", field="text")

    def width(self, text):
        return sum(self.glyph(c)[1] / self.glyph(c)[2] for c in text)

    def lines(self, value, width):
        lines = []
        for paragraph in value.splitlines():
            if not paragraph:
                lines.append("")
                continue
            line = ""
            for character in paragraph:
                if line and self.width(line + character) > width:
                    lines.append(line)
                    line = ""
                line += character
            lines.append(line)
        return lines

    def fill(self, values: dict[str, str], *, outline: bool = False) -> bytes:
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        from fontTools.pens.recordingPen import DecomposingRecordingPen
        root = ET.fromstring(self.svg)
        group = root.find(f"{{{NS}}}g[@id='dynamic-fields']")
        nodes = {node.get("id"): node for node in group}
        for field in self.fields:
            key = field["key"]
            value = str(values.get(key, ""))
            prefix = values.get(field.get("prefix_field", ""), "")
            display = field["format"].format(value=value, prefix=prefix) if value else ""
            for character in display.replace("\n", "").replace("\r", "") if field.get("multiline") else display:
                try:
                    self.glyph(character)
                except TemplatePdfError as exc:
                    raise TemplatePdfError(exc.code, f"{field['label']}：{exc}", field=key) from exc
            size, limit = field["font_size_mm"], field["max_width_mm"]
            if field.get("multiline"):
                display = ("技术要求\n" + value) if value else "技术要求"
                lines = self.lines(display, limit / size)
                if len(lines) * field["line_height_mm"] > field["max_height_mm"]:
                    raise TemplatePdfError("template_pdf_text_overflow", "技术要求超出图纸预留区域，请缩短内容后重新出图。", field=key)
            else:
                lines = [display]
                width = self.width(display)
                if width:
                    size = min(size, limit / width)
                if display and size < 2.0:
                    raise TemplatePdfError("template_pdf_text_overflow", f"{field['label']}过长，无法在可读字号下完整显示，请缩短内容。", field=key)
            node = nodes[field["id"]]
            for child in list(node):
                node.remove(child)
            node.attrib.pop("data-default", None)
            node.text = None
            node.set("font-size", str(size))
            baseline = field["y_mm"] + size * .82
            if "vertical_center_mm" in field:
                baseline = field["vertical_center_mm"] + size * field["baseline_offset_em"]
            node.set("y", str(baseline))
            if not outline:
                if len(lines) == 1:
                    node.text = lines[0]
                else:
                    for i, line in enumerate(lines):
                        span = ET.SubElement(node, f"{{{NS}}}tspan", {"x": str(field["x_mm"]), "y": str(baseline + i * field["line_height_mm"])})
                        span.text = line
                continue
            replacement = ET.Element(f"{{{NS}}}g", {"fill": field["color"], "data-field": key})
            if node.get("transform"):
                replacement.set("transform", node.get("transform"))
            for i, line in enumerate(lines):
                pen = SVGPathPen(None)
                advance = 0
                for character in line:
                    glyph, step, units, glyphset = self.glyph(character)
                    recording = DecomposingRecordingPen(glyphset)
                    glyph.draw(recording)
                    recording.replay(TransformPen(pen, (1/units, 0, 0, 1/units, advance, 0)))
                    advance += step / units
                offset = advance/2 if field["anchor"] == "middle" else advance if field["anchor"] == "end" else 0
                x = field["x_mm"] - offset * size
                y = baseline + i * field.get("line_height_mm", 0)
                ET.SubElement(replacement, f"{{{NS}}}path", {"d": pen.getCommands(), "transform": f"translate({x} {y}) scale({size} {-size})"})
            group.remove(node)
            group.append(replacement)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def render(self, values) -> tuple[bytes, bytes]:
        import pymupdf
        svg = self.fill(values)
        outlined = self.fill(values, outline=True)
        with pymupdf.open(stream=outlined, filetype="svg") as drawing:
            pdf = drawing.convert_to_pdf()
        with pymupdf.open(stream=pdf, filetype="pdf") as checked:
            if len(checked) != 1 or abs(checked[0].rect.width-595.276)>.1 or abs(checked[0].rect.height-841.89)>.1:
                raise TemplatePdfError("template_pdf_render_failed", "图纸版式校验失败，请重试。")
        return svg, pdf


def number(value) -> str:
    if value is None or isinstance(value, bool):
        return ""
    try:
        value = float(value)
        if math.isfinite(value):
            return f"{value:.4f}".rstrip("0").rstrip(".") or "0"
    except (TypeError, ValueError):
        pass
    return ""


def tolerance(item, *, percent=False):
    if percent:
        symmetric = item.get("tolerance_percent")
        if symmetric is not None:
            return f"±{number(symmetric)}%"
        upper, lower = item.get("tolerance_percent_upper"), item.get("tolerance_percent_lower")
    else:
        upper, lower = item.get("tolerance_upper"), item.get("tolerance_lower")
    if upper is None or lower is None:
        return ""
    suffix = "%" if percent else ""
    if upper == -lower and upper >= 0:
        return f"±{number(upper)}{suffix}"
    return f"{'+' if upper>=0 else ''}{number(upper)}{suffix}/{'+' if lower>=0 else ''}{number(lower)}{suffix}"


def build_snapshot(review: dict[str, Any]) -> dict[str, Any]:
    current = deepcopy(review)
    metric_review(current)
    package = build_generation_parameter_package(current, target="template_pdf")
    parameters = package["generation_parameters"]["spring_parameters"]
    projection = build_solidworks_technical_projection(package, current)
    original = current.get("spring_parameters") or {}
    calculation_parameters = {key: deepcopy(item) for key, item in original.items()
                              if isinstance(item, dict) and item.get("need_human_review") is False
                              and not any(item.get(flag) for flag in ("unit_pending", "conflict", "tolerance_input_draft"))
                              and parameter_current(original, key)}
    calculation_parameters["load_points"] = [deepcopy(item) for item in original.get("load_points") or []
                                            if isinstance(item, dict) and item.get("need_human_review") is False]
    checks = calculate_design_checks(calculation_parameters, current.get("spring_features") or {})
    source = package["source"]
    data = {key: "" for key in (
        "wire_diameter", "wire_diameter_tolerance", "outer_diameter", "outer_diameter_tolerance", "free_length", "total_coils", "active_coils", "handedness", "height1", "height2", "solid_height", "load1", "load2", "solid_load", "load1_tolerance", "load2_tolerance", "pitch", "surface_roughness_ra", "roughness_limit", "perpendicularity", "perpendicularity_grade", "spring_rate", "spring_index", "material", "product_name", "part_number", "technical_requirements", "customer_name", "drawing_date", "designer_name", "height1_label", "height2_label", "solid_height_label", "load1_label", "load2_label", "solid_load_label")}
    for key in ("wire_diameter", "free_length", "total_coils", "active_coils"):
        data[key] = number((parameters.get(key) or {}).get("value"))
    data["wire_diameter_tolerance"] = tolerance(parameters.get("wire_diameter") or {})
    data["free_length_tolerance"] = tolerance(parameters.get("free_length") or {})
    for key in ("height1_tolerance", "height2_tolerance", "solid_height_tolerance", "solid_load_tolerance"):
        data[key] = ""
    for key in ("outer_diameter", "pitch", "solid_height", "perpendicularity"):
        item = _confirmed_optional_mm(current.get("spring_parameters") or {}, key, allow_zero=key == "perpendicularity")
        if item:
            data[key] = number(item[1])
            if key == "outer_diameter":
                data["outer_diameter_tolerance"] = tolerance(item[0])
    if not data["outer_diameter"]:
        mean, wire = (parameters.get("mean_diameter") or {}).get("value"), (parameters.get("wire_diameter") or {}).get("value")
        if mean is not None and wire is not None:
            data["outer_diameter"] = number(mean + wire)
    data["wire_diameter_tolerance"] = tolerance(parameters.get("wire_diameter") or {})
    data["handedness"] = handedness_label((parameters.get("handedness") or {}).get("value")) if parameters.get("handedness") else ""
    material = (parameters.get("material") or {}).get("value")
    data["material"] = material_catalog_display_value(material) if isinstance(material, str) and material else ""
    data["product_name"] = source.get("drawing_name") or ""
    data["part_number"] = source.get("material_code") or ""
    settings = current.get("generation_settings") or {}
    data["designer_name"] = settings.get("username", "").strip() if isinstance(settings.get("username", ""), str) else ""
    data["technical_requirements"] = projection["text"]
    calculated_pitch = checks.get("pitch_calculation") or {}
    if not data["pitch"] and calculated_pitch.get("status") in {"calculated", "estimated"}:
        data["pitch"] = number(calculated_pitch.get("value"))
    for field, metric in (("spring_rate", "theoretical_spring_rate"), ("spring_index", "spring_index"), ("solid_height", "nominal_solid_height")):
        result = checks["metrics"].get(metric) or {}
        if not data[field] and result.get("status") in {"calculated", "estimated"}:
            data[field] = number(result.get("value"))
    roughness = confirmed_surface_roughness(current)
    if roughness:
        data["surface_roughness_ra"] = number(roughness["value"])
        data["roughness_limit"] = "≤" + data["surface_roughness_ra"]
    points = package["generation_parameters"]["load_points"]
    solid, working, issues = [], [], []
    for point in points:
        role = point.get("load_role")
        solid_label = _solid_label(point.get("label")) or str(point.get("height_label", "")).lower() == "hb"
        if role == "unknown" or role == "working" and solid_label:
            issues.append({"field": "load_points", "reason": f"载荷点 {point.get('label', '')} 的角色不明确或与编号冲突，请确认。"})
        elif role == "solid" or solid_label:
            solid.append(point)
        elif role == "working" or re.fullmatch(r"[FPfp]\d+", point.get("label", "")):
            working.append(point)
        else:
            issues.append({"field": "load_points", "reason": f"载荷点 {point.get('label', '')} 的工作/压并角色不明确，请确认。"})
    if len(working) > 2 or len(solid) > 1:
        issues.append({"field": "load_points", "reason": "当前模板最多支持两组工作载荷和一组压并载荷，请调整测试点或使用其他出图方式。"})
    force_labels = {point["label"].casefold() for point in points}
    height_values = {}
    for i, point in enumerate(working[:2], 1):
        suffix = re.search(r"\d+$", point["label"])
        height_label = point.get("height_label") or (f"H{suffix[0]}" if suffix else "")
        if not height_label:
            issues.append({"field": "load_points", "reason": f"载荷点 {point['label']} 无法匹配高度编号，请填写高度编号。"})
        height_key = height_label.casefold()
        if height_key in force_labels or height_key in {"h0", "d", "d1", "d2", "n", "n1", "t"}:
            issues.append({"field": "load_points", "reason": f"高度编号 {height_label} 与其他载荷或尺寸编号冲突，请修改。"})
        if height_key in height_values and height_values[height_key] != point["height"]:
            issues.append({"field": "load_points", "reason": f"高度编号 {height_label} 对应不同的高度或公差，请核对。"})
        height_values[height_key] = point["height"]
        data[f"height{i}"] = number(point["height"]["value"])
        data[f"load{i}"] = number(point["force"]["value"])
        data[f"load{i}_label"] = point["label"]
        data[f"height{i}_label"] = height_label
        data[f"load{i}_tolerance"] = tolerance(point["force"], percent=True) or tolerance(point["force"])
        data[f"height{i}_tolerance"] = tolerance(point["height"])
    if solid:
        data["solid_height"] = number(solid[0]["height"]["value"])
        data["solid_load"] = number(solid[0]["force"]["value"])
        data["solid_load_label"] = solid[0]["label"]
        data["solid_height_label"] = solid[0].get("height_label") or "Hb"
        data["solid_height_tolerance"] = tolerance(solid[0]["height"])
        data["solid_load_tolerance"] = tolerance(solid[0]["force"], percent=True) or tolerance(solid[0]["force"])
    elif data["solid_height"]:
        data["solid_height_label"] = "Hb"
    return {"schema_version": "template_pdf_parameters/v1", "parameter_package": package, "technical_requirements_projection": projection,
            "template_data": data, "calculation_snapshot": checks, "issues": issues}


def readiness(review: dict[str, Any], *, database_available=True):
    current = deepcopy(review)
    ready = assess_generation_readiness(current, target="template_pdf")
    snapshot = build_snapshot(current)
    asset = resource_status()
    blockers = list(snapshot["issues"])
    if not database_available:
        blockers.append({"field":"history", "reason":"模板 PDF 订单历史需要数据库，请先配置数据库。"})
    if not asset["available"]:
        blockers.append({"field":"template", "reason":asset["message"]})
    if asset["available"]:
        try:
            resources().fill(snapshot["template_data"])
        except TemplatePdfError as exc:
            blockers.extend(exc.detail()["issues"])
    ready["blocking_reasonableness"] = [*ready.get("blocking_reasonableness", []), *blockers]
    if blockers:
        ready.update(status="blocked", summary=blockers[0]["reason"])
    # Warnings are shared engineering findings, not a promise to run SW.
    for warning in ready.get("warnings", []):
        warning["reason"] = warning.get("reason", "").replace("SolidWorks", "图纸").replace("SW", "图纸")
    return {"readiness": ready, "resources": asset, "technical_requirements_projection": snapshot["technical_requirements_projection"]}, snapshot
