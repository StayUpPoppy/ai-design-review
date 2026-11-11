"""Geometry-backed bilingual height/force cells. Labels are identity hints only."""
from __future__ import annotations
import re
from .load_height_dimension import dimension_with_offsets, read_height_dimension

FORCE_HEADER = re.compile(r"(?:load|force|负荷|载荷|力值)\s*(?:[（(]\s*(?:N|kN|kgf)\s*[）)])?",re.I)


def table_height(point, texts):
    def cy(t): return (t["bbox"][1] + t["bbox"][3]) / 2
    def height(t): return max(1, t["bbox"][3] - t["bbox"][1])
    def row(t): return [v for v in texts if abs(cy(v) - cy(t)) <= max(height(v), height(t)) * .7]
    try:
        force = float(point["force"])
    except (ValueError, TypeError, KeyError):
        return None
    force_unit=point.get("force_unit") or "N"
    force_cell_pattern=re.compile(rf"([+-]?\d+(?:\.\d+)?)\s*(?:{re.escape(force_unit)})?",re.I)
    numeric = [(t, float(match[1])) for t in texts if (match:=force_cell_pattern.fullmatch(t["text"].strip()))]
    # OCR rotations may split a whole number into contained digit boxes; never join cells.
    numeric = [(t,x) for t,x in numeric if not any(len(v["text"]) > len(t["text"]) and t["text"] in v["text"]
               and v["bbox"][0]-height(v)*.2<=t["bbox"][0] and v["bbox"][1]-height(v)*.2<=t["bbox"][1]
               and v["bbox"][2]+height(v)*.2>=t["bbox"][2] and v["bbox"][3]+height(v)*.2>=t["bbox"][3] for v,_ in numeric)]
    height_cells=[(t,parsed["value"]) for t in texts if (parsed:=read_height_dimension(t["text"])) and parsed["unit"].lower() in {"mm","毫米"}]
    # The dimension parser also reads a single digit from split OCR boxes.
    height_cells=[(t,x) for t,x in height_cells if not any(len(v["text"])>len(t["text"]) and t["text"] in v["text"]
                  and v["bbox"][0]-height(v)*.2<=t["bbox"][0] and v["bbox"][1]-height(v)*.2<=t["bbox"][1]
                  and v["bbox"][2]+height(v)*.2>=t["bbox"][2] and v["bbox"][3]+height(v)*.2>=t["bbox"][3] for v,_ in height_cells)]
    force_cells = []
    for t, value in numeric:
        if abs(value - force) > 1e-7 or point.get("_force_bbox") and point["_force_bbox"]!=t["bbox"]:
            continue
        cells = row(t)
        labels = [v for v in cells if v["bbox"][2] < t["bbox"][0] and re.search(r"\b(?:load|force)\b|负荷|载荷|力值", v["text"], re.I)]
        units = [v for v in cells if re.search(rf"(?<![A-Za-z]){re.escape(point.get('force_unit') or 'N')}(?![A-Za-z/])", v["text"])]
        if labels and units:
            force_cells.append(t)
    matches = []
    # Horizontal tables: a header owns a column; the force and height own one row.
    for f,value in numeric:
        if abs(value-force)>1e-7 or point.get("_force_bbox") and point["_force_bbox"]!=f["bbox"]:continue
        headers=[t for t in texts if FORCE_HEADER.fullmatch(t["text"].strip())
                 and 0<cy(f)-cy(t)<12*height(t)]
        for header in headers:
            peers=row(header)
            columns=sorted(peers,key=lambda t:(t["bbox"][0]+t["bbox"][2])/2)
            def owns(label,cell):
                center=(label["bbox"][0]+label["bbox"][2])/2
                others=[(t["bbox"][0]+t["bbox"][2])/2 for t in columns if t is not label]
                lo=max([x for x in others if x<center],default=center-2*max(20,label["bbox"][2]-label["bbox"][0]))
                hi=min([x for x in others if x>center],default=center+2*max(20,label["bbox"][2]-label["bbox"][0]))
                return (lo+center)/2<(cell["bbox"][0]+cell["bbox"][2])/2<(center+hi)/2
            if not owns(header,f):continue
            def unit_at(label,unit):
                return bool(re.search(rf"(?<![A-Za-z]){unit}(?![A-Za-z/])",label["text"],re.I)) or any(
                    0<cy(t)-cy(label)<2*height(label) and owns(label,t) and re.fullmatch(rf"\s*[（(]?{unit}[）)]?\s*",t["text"],re.I) for t in texts)
            if not unit_at(header,re.escape(point.get("force_unit") or "N")):continue
            for label in peers:
                if not re.fullmatch(r"(?:height|working\s+height|installed\s+height|高度|工作高度|安装高度)\s*(?:[（(]\s*(?:mm|毫米)\s*[）)])?",label["text"].strip(),re.I) or not unit_at(label,"mm|毫米"):continue
                values=[(t,x) for t,x in height_cells if t in row(f) and owns(label,t)]
                if len({x for _,x in values})==1:
                    t,x=values[0];matches.append((0,x,t,label,f))
    for f in force_cells:
        candidates = []
        for label in texts:
            if not re.fullmatch(r"(?:height|(?:installed|working|test)\s+height|高度|安装高度|工作高度|测试高度)", label["text"].strip(), re.I):
                continue
            if abs(cy(label) - cy(f)) > 2.5 * max(height(f), height(label)) or label["bbox"][0] >= f["bbox"][0]:
                continue
            if any(min(cy(label),cy(f))+.7*max(height(label),height(f))<cy(t)<max(cy(label),cy(f))-.7*max(height(label),height(f)) and re.fullmatch(r"load|force|载荷|负荷|力值",t["text"].strip(),re.I) for t in texts):
                continue
            cells = row(label)
            if not any(re.search(r"\bmm\b|毫米", v["text"], re.I) for v in cells):
                continue
            values = [(v, x) for v, x in height_cells if v in cells and v["bbox"][0] > label["bbox"][2]
                      and abs((v["bbox"][0] + v["bbox"][2] - f["bbox"][0] - f["bbox"][2]) / 2)
                      < max(v["bbox"][2] - v["bbox"][0], f["bbox"][2] - f["bbox"][0])]
            if len({x for _, x in values}) == 1:
                v, x = values[0]
                candidates.append((abs(cy(label) - cy(f)), x, v, label))
        if candidates:
            candidates.sort(key=lambda v: v[0])
            best = candidates[0]
            if any(abs(v[0] - best[0]) < height(f) * .5 and v[1] != best[1] for v in candidates[1:]):
                continue
            matches.append((*best, f))
    if not matches:
        return None
    if len({v[1] for v in matches}) != 1:
        return {"conflict": True}
    _, value, cell, label, force_cell = matches[0]
    dimension, evidence=dimension_with_offsets(cell,texts,cell["bbox"][3])
    return {"value": value, "cell": evidence, "force_cell": force_cell, "dimension":dimension,
            "evidence": f"{label['text']} (mm) {value:g}; Load {force:g} {point.get('force_unit') or 'N'}"}
