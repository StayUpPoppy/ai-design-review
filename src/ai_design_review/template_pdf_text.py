"""Shared SVG text geometry and outlined glyphs for the drawing renderer."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import math
from xml.etree import ElementTree as ET

NS = "http://www.w3.org/2000/svg"


class TemplatePdfError(ValueError):
    def __init__(self, code: str, message: str, *, field: str = "template", issues: list | None = None):
        super().__init__(message)
        self.code, self.field, self.issues = code, field, issues or []

    def detail(self):
        return {"code": self.code, "message": str(self), "issues": self.issues or [{"field": self.field, "reason": str(self)}]}


@dataclass(frozen=True)
class TextRun:
    text: str
    x: float
    y: float
    size: float
    role: str = "value"


def union(rectangles):
    rectangles = [item for item in rectangles if item is not None]
    return (min(r[0] for r in rectangles), min(r[1] for r in rectangles),
            max(r[2] for r in rectangles), max(r[3] for r in rectangles)) if rectangles else None


def rotate_bounds(rect, angle, origin):
    if not rect or not angle:
        return rect
    radians = math.radians(angle)
    c, s = math.cos(radians), math.sin(radians)
    ox, oy = origin
    points = [(ox+c*(x-ox)-s*(y-oy), oy+s*(x-ox)+c*(y-oy))
              for x in (rect[0], rect[2]) for y in (rect[1], rect[3])]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def touches_segment(rect, segment, margin=.18):
    """Clip a segment against a padded ink rectangle (Liang–Barsky)."""
    left, top, right, bottom = rect[0]-margin, rect[1]-margin, rect[2]+margin, rect[3]+margin
    (x1, y1), (x2, y2) = segment
    lo, hi = 0.0, 1.0
    for p, q in ((x1-x2, x1-left), (x2-x1, right-x1), (y1-y2, y1-top), (y2-y1, bottom-y1)):
        if abs(p)<1e-12:
            if q<0:
                return False
        elif p<0:
            lo = max(lo, q/p)
        else:
            hi = min(hi, q/p)
        if lo>hi:
            return False
    return True


class VectorText:
    def __init__(self, font_paths):
        from fontTools.ttLib import TTFont
        self.fonts = []
        for path in font_paths:
            font = TTFont(path, fontNumber=0)
            self.fonts.append((font.getBestCmap(), font.getGlyphSet(), font["hmtx"].metrics, font["head"].unitsPerEm))

    def glyph(self, character):
        for cmap, glyphs, metrics, units in self.fonts:
            name = cmap.get(ord(character))
            if name is not None:
                return glyphs[name], metrics[name][0], units, glyphs
        raise TemplatePdfError("template_pdf_missing_glyph", f"图纸字体不支持字符“{character}”，请修改对应文字。", field="text")

    def width(self, text):
        return sum(self.glyph(character)[1]/self.glyph(character)[2] for character in text)

    @lru_cache(maxsize=4096)
    def character_bounds(self, character):
        from fontTools.pens.boundsPen import BoundsPen
        glyph, _, units, glyphset = self.glyph(character)
        pen = BoundsPen(glyphset)
        glyph.draw(pen)
        return tuple(value/units for value in pen.bounds) if pen.bounds else None

    def bounds(self, runs):
        rectangles = []
        for run in runs:
            advance = 0
            for character in run.text:
                box = self.character_bounds(character)
                if box:
                    rectangles.append((run.x+(advance+box[0])*run.size, run.y-box[3]*run.size,
                                       run.x+(advance+box[2])*run.size, run.y-box[1]*run.size))
                advance += self.glyph(character)[1]/self.glyph(character)[2]
        return union(rectangles)

    def element(self, runs, attributes, *, outline):
        attributes = {str(k): str(v) for k, v in attributes.items()}
        attributes["text-anchor"] = "start"
        if not outline:
            node = ET.Element(f"{{{NS}}}text", {**attributes, "font-family": "FangSong, SimSun, serif"})
            if len(runs) == 1:
                run = runs[0]
                node.attrib.update(x=str(run.x), y=str(run.y), **{"font-size": str(run.size)})
                node.text = run.text
            else:
                for run in runs:
                    span = ET.SubElement(node, f"{{{NS}}}tspan", {
                        "x": str(run.x), "y": str(run.y), "font-size": str(run.size), "data-role": run.role,
                    })
                    span.text = run.text
            return node
        from fontTools.pens.recordingPen import DecomposingRecordingPen
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        node = ET.Element(f"{{{NS}}}g", attributes)
        for run in runs:
            pen = SVGPathPen(None)
            advance = 0
            for character in run.text:
                glyph, step, units, glyphset = self.glyph(character)
                recording = DecomposingRecordingPen(glyphset)
                glyph.draw(recording)
                recording.replay(TransformPen(pen, (1/units, 0, 0, 1/units, advance, 0)))
                advance += step/units
            ET.SubElement(node, f"{{{NS}}}path", {
                "d": pen.getCommands(), "transform": f"translate({run.x} {run.y}) scale({run.size} {-run.size})",
                "data-role": run.role, "data-font-size-mm": str(run.size),
            })
        return node

    def annotation_runs(self, field, values, size):
        value = str(values.get(field["key"], ""))
        if not value:
            return []
        prefix = str(values.get(field.get("prefix_field", ""), ""))
        nominal = field["format"].format(value=value, prefix=prefix)
        tolerance = str(values.get(field.get("tolerance_field", ""), ""))
        unit = field.get("unit", "")
        percentage = "%" in tolerance
        suffix = f" {unit}" if unit and not percentage else ""
        if unit and percentage:
            nominal += f" {unit}"
        if not tolerance:
            return [TextRun(nominal+suffix, 0, 0, size)]
        if "/" not in tolerance:
            return [TextRun(nominal+(" " if percentage else "")+tolerance+suffix, 0, 0, size)]
        upper, lower = tolerance.split("/", 1)
        smaller = max(2.0, size*.75)
        x = self.width(nominal)*size+size*.18
        runs = [TextRun(nominal, 0, 0, size), TextRun(upper, x, -.45*size, smaller, "tolerance-upper"),
                TextRun(lower, x, .45*size, smaller, "tolerance-lower")]
        if suffix:
            tail = x+max(self.width(upper), self.width(lower))*smaller+size*.12
            runs.append(TextRun(suffix, tail, 0, size, "unit"))
        return runs

    def place(self, field, values, obstacles=(), occupied=()):
        """Fit a complete annotation, including the actual signed tolerance ink."""
        value = str(values.get(field["key"], ""))
        if not value:
            return []
        size = float(field["font_size_mm"])
        box = field.get("box_mm")
        if field.get("avoid_overlap") and obstacles:
            origin = (field["x_mm"], field["y_mm"])
            angle = field.get("rotation", 0)
            if box:
                region = union(rotate_bounds(candidate, angle, origin) for candidate in (box, field.get("alternate_box_mm")) if candidate)
            else:
                width = field["max_width_mm"]
                region = rotate_bounds((origin[0]-width-1,origin[1]-size*2,origin[0]+width+1,origin[1]+size*2),angle,origin)
            obstacles = [segment for segment in obstacles
                         if max(segment[0][0],segment[1][0])>=region[0]-.2 and min(segment[0][0],segment[1][0])<=region[2]+.2
                         and max(segment[0][1],segment[1][1])>=region[1]-.2 and min(segment[0][1],segment[1][1])<=region[3]+.2]
        while size >= 2.0-1e-8:
            runs = self.annotation_runs(field, values, max(size, 2.0))
            bounds = self.bounds(runs)
            if bounds and bounds[2]-bounds[0] <= field["max_width_mm"]+1e-7 and (not box or bounds[3]-bounds[1] <= box[3]-box[1]+1e-7):
                if box:
                    width = bounds[2]-bounds[0]
                    anchor = field.get("preferred_x_mm", (box[0]+box[2])/2)
                    preferred = anchor if field.get("anchor") == "start" else anchor-width if field.get("anchor") == "end" else anchor-width/2
                    preferred = min(max(preferred, box[0]), box[2]-width)
                    dx = preferred-bounds[0]
                    dy = box[3]-bounds[3] if field.get("vertical_align") == "bottom" else (box[1]+box[3]-bounds[1]-bounds[3])/2
                else:
                    anchor = field["x_mm"]
                    dx = anchor-bounds[0] if field["anchor"] == "start" else anchor-bounds[2] if field["anchor"] == "end" else anchor-(bounds[0]+bounds[2])/2
                    dy = field["y_mm"]+size*.82
                    if "vertical_center_mm" in field:
                        dy = field["vertical_center_mm"]-(bounds[1]+bounds[3])/2
                offsets = [dx]
                if box and field.get("avoid_overlap"):
                    left, right = box[0]-bounds[0], box[2]-bounds[2]
                    offsets += sorted({left, right, *[left+i*.5 for i in range(max(0, int((right-left)/.5)+1))]}, key=lambda x:abs(x-dx))
                for offset in offsets:
                    translated = (bounds[0]+offset,bounds[1]+dy,bounds[2]+offset,bounds[3]+dy)
                    ink = rotate_bounds(translated, field.get("rotation", 0), (field["x_mm"], field["y_mm"]))
                    if field.get("avoid_overlap") and (
                        any(touches_segment(ink, segment) for segment in obstacles)
                        or any(ink[0]<other[2]+.25 and ink[2]>other[0]-.25 and ink[1]<other[3]+.25 and ink[3]>other[1]-.25 for other in occupied)
                    ):
                        continue
                    return [replace(run, x=run.x+offset, y=run.y+dy) for run in runs]
            if size <= 2.0+1e-8:
                break
            size = max(2.0, round(size-.05, 8))
        if field.get("alternate_box_mm"):
            alternative = {**field, "box_mm": field["alternate_box_mm"]}
            alternative.pop("alternate_box_mm")
            return self.place(alternative, values, obstacles, occupied)
        raise TemplatePdfError("template_pdf_text_overflow", f"{field['label']}及公差过长，无法完整显示，请调整内容。", field=field["key"])
