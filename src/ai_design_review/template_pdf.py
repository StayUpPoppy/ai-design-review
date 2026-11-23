"""Fixed SVG drawing data, layout and vector PDF rendering, independent of SW."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
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
from .engineering_units import metric_review
from .solidworks import build_solidworks_technical_projection, _confirmed_optional_mm, _solid_label
from .surface_roughness import confirmed_surface_roughness
from .material_catalog import material_catalog_display_value
from .standardizers.design_checks import calculate_design_checks
from .standardizers.calculation_state import parameter_current
from .template_pdf_text import TemplatePdfError, TextRun, VectorText, rotate_bounds

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
MAPPING_VERSION = 3
DATA_SCHEMA = "template_pdf_parameters/v3"
DATA_KEYS = frozenset("""
    wire_diameter wire_diameter_tolerance outer_diameter outer_diameter_tolerance
    free_length free_length_tolerance
    height1 height2 solid_height load1 load2 solid_load load1_tolerance load2_tolerance
    height1_tolerance height2_tolerance solid_height_tolerance solid_load_tolerance
    pitch pitch_tolerance surface_roughness_ra perpendicularity
    spring_rate spring_index solid_stress material product_name customer_code material_code weight_kg
    technical_requirements designer_name
    height1_label height2_label solid_height_label load1_label load2_label solid_load_label
""".split())


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


class Resources(VectorText):
    def __init__(self, paths):
        self.svg = paths[0].read_bytes()
        self.manifest = json.loads(paths[1].read_text(encoding="utf-8"))
        if self.manifest.get("mapping_version") != MAPPING_VERSION:
            raise TemplatePdfError("template_pdf_resource_version_mismatch", "模板资源版本不匹配，请更新 35-9 模板资源包后重新出图。")
        self.fields = self.manifest["templates"][0]["fields"]
        self.keys = {item["key"] for item in self.fields}
        self.keys.update(field[key] for field in self.fields for key in ("prefix_field", "tolerance_field") if field.get(key))
        if self.keys != DATA_KEYS:
            raise TemplatePdfError("template_pdf_resource_version_mismatch", "模板字段与当前程序不匹配，请更新 35-9 模板资源包后重新出图。")
        root = ET.fromstring(self.svg)
        if root.get("viewBox") != "0 0 210 297":
            raise ValueError("A4 template expected")
        group = root.find(f"{{{NS}}}g[@id='dynamic-fields']")
        if group is None:
            raise ValueError("Missing dynamic field group")
        nodes = {e.get("id") for e in group if e.get("data-field")}
        if len(nodes) != len(self.fields) or nodes != {f["id"] for f in self.fields}:
            raise ValueError("Field manifest and SVG do not match")
        by_id = {node.get("id"): node for node in group}
        if any(by_id[field["id"]].get("data-field") != field["key"] for field in self.fields):
            raise ValueError("SVG field keys do not match the manifest")
        super().__init__(paths[2:])
        self.version = sha256(b"".join(path.read_bytes() for path in paths)).hexdigest()
        self.obstacles = self._drawing_segments()

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

    def _drawing_segments(self):
        import pymupdf
        segments = []
        factor = 25.4/72
        with pymupdf.open(stream=self.svg, filetype="svg") as source:
            pdf = source.convert_to_pdf()
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            for drawing in document[0].get_drawings():
                if drawing["rect"].y0*factor > 140:
                    continue
                for item in drawing["items"]:
                    pairs = []
                    if item[0] == "l":
                        pairs = [(item[1], item[2])]
                    elif item[0] == "re":
                        rect = item[1]
                        corners = [rect.top_left, rect.top_right, rect.bottom_right, rect.bottom_left, rect.top_left]
                        pairs = list(zip(corners, corners[1:]))
                    elif item[0] == "c":
                        p0, p1, p2, p3 = item[1:]
                        points = []
                        for i in range(17):
                            t = i/16
                            coefficients = ((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3)
                            points.append(pymupdf.Point(sum(c*p.x for c,p in zip(coefficients,(p0,p1,p2,p3))),
                                                       sum(c*p.y for c,p in zip(coefficients,(p0,p1,p2,p3)))))
                        pairs = list(zip(points, points[1:]))
                    for start, end in pairs:
                        if math.hypot(end.x-start.x,end.y-start.y)*factor >= .02:
                            segments.append(((start.x*factor, start.y*factor), (end.x*factor, end.y*factor)))
        return segments

    def layout(self, values):
        placements, occupied = [], []
        for field in self.fields:
            key = field["key"]
            try:
                if field.get("multiline"):
                    size = field["font_size_mm"]
                    value = str(values.get(key, ""))
                    lines = self.lines("技术要求"+("\n"+value if value else ""), field["max_width_mm"]/size)
                    if len(lines)*field["line_height_mm"] > field["max_height_mm"]:
                        raise TemplatePdfError("template_pdf_text_overflow", "技术要求超出图纸预留区域，请缩短内容后重新出图。", field=key)
                    runs = [TextRun(line, field["x_mm"], field["y_mm"]+size*.82+i*field["line_height_mm"], size, "line") for i, line in enumerate(lines)]
                else:
                    runs = self.place(field, values, self.obstacles, occupied)
                bounds = rotate_bounds(self.bounds(runs), field.get("rotation", 0), (field["x_mm"], field["y_mm"]))
                if bounds and field.get("avoid_overlap"):
                    occupied.append(bounds)
                placements.append((field, runs, bounds))
            except TemplatePdfError as exc:
                if exc.code == "template_pdf_missing_glyph":
                    raise TemplatePdfError(exc.code, f"{field['label']}：{exc}", field=key) from exc
                raise
        return placements

    def fill(self, values: dict[str, str], *, outline: bool = False) -> bytes:
        root = ET.fromstring(self.svg)
        group = root.find(f"{{{NS}}}g[@id='dynamic-fields']")
        for node in list(group):
            group.remove(node)
        for field, runs, bounds in self.layout(values):
            attributes = {"id": field["id"], "data-field": field["key"], "fill": field["color"]}
            if field.get("rotation"):
                attributes["transform"] = f"rotate({field['rotation']} {field['x_mm']} {field['y_mm']})"
            if bounds:
                attributes["data-ink-bounds"] = " ".join(f"{value:.6f}" for value in bounds)
            group.append(self.element(runs, attributes, outline=outline))
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


def weight_number(value) -> str:
    """Round positive kg values to three decimals, preserving a tiny-value limit."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite() or parsed <= 0:
            return ""
        with localcontext() as context:
            context.prec = max(28, parsed.adjusted()+5)
            rounded = parsed.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return format(rounded, "f").rstrip("0").rstrip(".") if rounded else "<0.001"
    except (TypeError, ValueError, InvalidOperation):
        return ""


def tolerance(item, *, percent=False):
    def text(value):
        from .solidworks import _tolerance_number
        return _tolerance_number(float(value))
    if percent:
        symmetric = item.get("tolerance_percent")
        if symmetric is not None:
            return f"±{text(symmetric)}%" if isinstance(symmetric, (int, float)) and not isinstance(symmetric, bool) and math.isfinite(symmetric) and symmetric>=0 else ""
        upper, lower = item.get("tolerance_percent_upper"), item.get("tolerance_percent_lower")
    else:
        upper, lower = item.get("tolerance_upper"), item.get("tolerance_lower")
    if upper is None or lower is None:
        return ""
    if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in (upper,lower)) or upper<lower:
        return ""
    suffix = "%" if percent else ""
    if upper == -lower and upper >= 0:
        return f"±{text(upper)}{suffix}"
    return f"{'+' if upper>=0 else ''}{text(upper)}{suffix}/{'+' if lower>=0 else ''}{text(lower)}{suffix}"


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
    data = dict.fromkeys(sorted(DATA_KEYS), "")
    for key in ("wire_diameter", "free_length"):
        data[key] = number((parameters.get(key) or {}).get("value"))
    data["wire_diameter_tolerance"] = tolerance(parameters.get("wire_diameter") or {})
    data["free_length_tolerance"] = tolerance(parameters.get("free_length") or {})
    for key in ("outer_diameter", "pitch", "solid_height", "perpendicularity"):
        item = _confirmed_optional_mm(current.get("spring_parameters") or {}, key, allow_zero=key == "perpendicularity")
        if item:
            data[key] = number(item[1])
            if key in {"outer_diameter", "pitch", "solid_height"}:
                data[key+"_tolerance"] = tolerance(item[0])
    if not data["outer_diameter"]:
        mean, wire = (parameters.get("mean_diameter") or {}).get("value"), (parameters.get("wire_diameter") or {}).get("value")
        if mean is not None and wire is not None:
            data["outer_diameter"] = number(mean + wire)
    data["wire_diameter_tolerance"] = tolerance(parameters.get("wire_diameter") or {})
    material = (parameters.get("material") or {}).get("value")
    data["material"] = material_catalog_display_value(material) if isinstance(material, str) and material else ""
    data["product_name"] = source.get("drawing_name") or ""
    data["customer_code"] = source.get("drawing_no") or ""
    data["material_code"] = source.get("material_code") or ""
    settings = current.get("generation_settings") or {}
    data["designer_name"] = settings.get("username", "").strip() if isinstance(settings.get("username", ""), str) else ""
    data["technical_requirements"] = projection["text"]
    calculated_pitch = checks.get("pitch_calculation") or {}
    if not data["pitch"] and calculated_pitch.get("status") in {"calculated", "estimated"}:
        data["pitch"] = number(calculated_pitch.get("value"))
    for field, metric in (("spring_rate", "theoretical_spring_rate"), ("spring_index", "spring_index"), ("solid_stress", "solid_stress"), ("solid_height", "nominal_solid_height")):
        result = checks["metrics"].get(metric) or {}
        if not data[field] and result.get("status") in {"calculated", "estimated"}:
            data[field] = number(result.get("value"))
    mass = checks["metrics"].get("unit_mass") or {}
    if mass.get("status") in {"calculated", "estimated"} and mass.get("unit") == "kg":
        data["weight_kg"] = weight_number(mass.get("value"))
    roughness = confirmed_surface_roughness(current)
    if roughness:
        data["surface_roughness_ra"] = number(roughness["value"])
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
        previous_height = data["solid_height"]
        previous_tolerance = data["solid_height_tolerance"]
        data["solid_height"] = number(solid[0]["height"]["value"])
        data["solid_load"] = number(solid[0]["force"]["value"])
        data["solid_load_label"] = solid[0]["label"]
        data["solid_height_label"] = solid[0].get("height_label") or "Hb"
        data["solid_height_tolerance"] = tolerance(solid[0]["height"]) or (previous_tolerance if previous_height == data["solid_height"] else "")
        data["solid_load_tolerance"] = tolerance(solid[0]["force"], percent=True) or tolerance(solid[0]["force"])
    elif data["solid_height"]:
        data["solid_height_label"] = "Hb"
    return {"schema_version": DATA_SCHEMA, "parameter_package": package, "technical_requirements_projection": projection,
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
