"""Match original load stations before allocating display labels."""
from __future__ import annotations

import math
import re
import unicodedata

from .load_height_relations import millimeters, number
from .load_units import FORCE_UNITS


def value(point):
    return point.get("value", point)


def relation(point):
    return value(point).get("height_relation") or {}


def context(point):
    return {**(value(point).get("source_context") or {}), **(point.get("source_context") or {})}


def sources(point):
    names = point.get("source") or []
    return set(names if isinstance(names, list) else [names])


def scope(point):
    page = number(point.get("page", value(point).get("page", 1)))
    return int(page) if page is not None and page >= 1 else 1, relation(point).get("scope") or ""


def _normalized(text):
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def explicit_label(point, field="label"):
    label = str(value(point).get(field) or "").strip()
    if not label or context(point).get("force_label_inferred" if field == "label" else "height_label_inferred"):
        return ""
    if "qwen_vision" not in sources(point) or "local_load_evidence" in sources(point):
        return label
    evidence = "\n".join(_normalized(text) for text in (
        point.get("evidence"), relation(point).get("evidence"), context(point).get("row_text"),
        *context(point).get("headers", []),
    ))
    token = re.escape(_normalized(label))
    # A symbol must be quoted as part of the original value or table header.
    if re.search(rf"(?<![A-Za-z0-9_]){token}(?![A-Za-z0-9_])(?:\s*[=:]\s*(?:[+\-]?\d|[HL]\d*\s*=)|\s+\d|\s*\(\s*(?:mm|k?N|kgf)\s*\))", evidence, re.I):
        return label
    if any(_normalized(header).casefold() == label.casefold() for header in context(point).get("headers", [])):
        return label
    return ""


def _xy(point):
    if isinstance(point, dict):
        x, y = number(point.get("x")), number(point.get("y"))
        if x is not None and y is not None and 0 <= x <= 1 and 0 <= y <= 1:
            return x, y
    return None


def _center(box):
    if isinstance(box, dict) and box.get("coordinate_type") in {"normalized", "relative"} and (xy := _xy(box)):
        w, h = number(box.get("width")), number(box.get("height"))
        if w is not None and h is not None and w > 0 and h > 0:
            return xy if box.get("origin") == "center" else (xy[0] + w / 2, xy[1] + h / 2)
    return None


def _geometry(point):
    return relation(point).get("geometry_evidence") or {}


def station_position(point):
    """Only original geometry and localized source boxes establish position."""
    if "local_load_evidence" in sources(point):
        anchor = _xy(_geometry(point).get("load_anchor"))
        if anchor:
            return "graph", anchor
        if xy := _center(point.get("position") or value(point).get("position")):
            return "table" if relation(point).get("verification_method") == "table_cells" else "mark", xy
    if sources(point) & {"pdf_text_layer", "cad", "dxf", "dwg"} and (xy := _center(point.get("position"))):
        return "mark", xy
    return None


def _near(left, right, tolerance=.008):
    return max(abs(a - b) for a, b in zip(left, right)) <= tolerance


def same_station(left, right):
    if scope(left) != scope(right):
        return False
    a, b = station_position(left), station_position(right)
    if a and b:
        if a[0] == b[0]:
            return _near(a[1], b[1], .004 if a[0] == "table" else .008)
        if "mark" in {a[0], b[0]}:
            left_mark, right_mark = _center(left.get("position")), _center(right.get("position"))
            return bool(left_mark and right_mark and _near(left_mark, right_mark, .004))
        return False
    # A model location is only useful against a unique, independently verified
    # contact and a matching height datum from the same drawing.
    grounded, draft = (a, right) if a else (b, left)
    original = left if a else right
    if not grounded or grounded[0] != "graph" or "qwen_vision" not in sources(draft):
        return False
    hint = relation(draft).get("graphic_hint") or {}
    contact, datum, actual_datum = _xy(hint.get("load_contact")), _xy(hint.get("datum")), _xy(_geometry(original).get("datum"))
    return bool(contact and datum and actual_datum and _near(grounded[1], contact) and _near(datum, actual_datum, .02))


def force_newtons(amount, unit):
    factor = FORCE_UNITS.get(str(unit or "").strip().casefold().replace("牛顿", "牛"))
    amount = number(amount)
    return amount * factor if amount is not None and factor is not None else None


def readings(point):
    item, height_relation = value(point), relation(point)
    height = millimeters(item.get("height"), item.get("height_unit"))
    if height is None and height_relation.get("kind") == "absolute_height":
        height = millimeters(height_relation.get("value"), height_relation.get("unit"))
    force = force_newtons(item.get("force"), item.get("force_unit"))
    return force if force is not None and force >= 0 else None, height if height is not None and height > 0 else None


def _equal_readings(left, right):
    return all(a is not None and b is not None and math.isclose(a, b, rel_tol=0, abs_tol=1e-7)
               for a, b in zip(readings(left), readings(right)))


def _chart_kind(point):
    kind = context(point).get("kind")
    if kind == "table" or relation(point).get("verification_method") == "table_cells":
        return "table"
    if kind == "load_graph" or re.search(r"曲线|图形|尺寸线|load\s+graph|load\s+curve", str(point.get("evidence") or "") + str(relation(point).get("evidence") or ""), re.I):
        return "graph"
    return ""


def _connected_chart(left, right):
    a, b = _geometry(left), _geometry(right)
    for first in a.get("curve_segment", []):
        for second in b.get("curve_segment", []):
            x, y = _xy(first), _xy(second)
            if x and y and _near(x, y, .012):
                return True
    return False


def _same_chart(grounded, draft, all_points):
    kind = _chart_kind(grounded)
    if kind == "table":
        a, b = context(grounded).get("table_title"), context(draft).get("table_title")
        return _chart_kind(draft) == kind and bool(a and b and _normalized(a).casefold() == _normalized(b).casefold())
    if kind != "graph" or _chart_kind(draft) != kind:
        return False
    peers = [p for p in all_points if scope(p) == scope(grounded) and station_position(p) and _chart_kind(p) == kind]
    # Unpositioned readings may attach to a single independently located graph.
    connected = [grounded]
    while waiting := [p for p in peers if p not in connected]:
        linked = [p for p in waiting if any(same_station(p, other) or _connected_chart(p, other) for other in connected)]
        if not linked:
            return False
        connected.extend(linked)
    return True


def _same_original_name(left, right):
    a, b = explicit_label(left), explicit_label(right)
    if not a and b and _legacy_model_name(left):
        a = _legacy_model_name(left)
    if not b and a and _legacy_model_name(right):
        b = _legacy_model_name(right)
    return bool(a and b and a.casefold() == b.casefold())


def _legacy_model_name(point):
    if ("qwen_vision" in sources(point) and "force_label_inferred" not in context(point)
            and not point.get("evidence") and not relation(point).get("evidence") and not context(point).get("row_text")):
        return str(value(point).get("label") or "").strip()
    return ""


def _name_conflict(left, right):
    return any(a and b and a.casefold() != b.casefold() for a, b in (
        (explicit_label(left, field), explicit_label(right, field)) for field in ("label", "height_label")
    ))


def _numeric_match(left, right, all_points):
    a, b = station_position(left), station_position(right)
    if bool(a) == bool(b) or _name_conflict(left, right) or not _equal_readings(left, right) or any(
        value(point).get(field) for point in (left, right) for field in ("load_force_conflict", "load_height_conflict")
    ):
        return False
    grounded, draft = (left, right) if a else (right, left)
    hint = _xy((relation(draft).get("graphic_hint") or {}).get("load_contact"))
    return ("qwen_vision" in sources(draft) and (not hint or _near((a or b)[1], hint))
            and _same_chart(grounded, draft, all_points))


def match_rank(left, right, all_points):
    if scope(left) != scope(right):
        return 0
    if same_station(left, right):
        return 3
    a, b = station_position(left), station_position(right)
    if a and b or _name_conflict(left, right):
        return 0
    titles = [_normalized(context(point).get("table_title")).casefold() for point in (left, right)]
    if all(titles) and titles[0] != titles[1]:
        return 0
    locations = [position[1] if position and position[0] == "graph" else _xy((relation(point).get("graphic_hint") or {}).get("load_contact"))
                 for point, position in ((left, a), (right, b))]
    if all(locations) and not _near(*locations):
        return 0
    if _same_original_name(left, right):
        return 2
    if _numeric_match(left, right, all_points):
        return 1
    return 0


def unique_match(point, options, all_points):
    ranked = [(match_rank(point, other, all_points), other) for other in options]
    best = max((rank for rank, _ in ranked), default=0)
    return [other for rank, other in ranked if best and rank == best]


def group_load_points(points):
    """Attach drafts only to one compatible station, with reciprocal value matching."""
    groups = []
    for point in sorted(points, key=lambda p: not bool(station_position(p))):
        compatible = []
        for group in groups:
            anchored = [member for member in group if station_position(member)]
            if anchored and all(same_station(point, member) for member in anchored):
                compatible.append(group)
        if len(compatible) == 1:
            compatible[0].append(point)
        else:
            groups.append([point])
    for minimum in (2, 1):
        index = 0
        while index < len(groups):
            group = groups[index]
            if len(group) > 1 or station_position(group[0]):
                index += 1
                continue
            point = group[0]
            options = [other for other in groups if other is not group and any(match_rank(point, member, points) == minimum for member in other)
                       and all(not _name_conflict(point, member) for member in other)]
            if minimum == 2:
                located = [other for other in options if any(station_position(member) for member in other)]
                if located:
                    options = located
                elif len(options) > 1:
                    corroborating = [member for other in options for member in other]
                    if all(match_rank(a, b, points) == 2 for i, a in enumerate(corroborating) for b in corroborating[i+1:]):
                        group.extend(corroborating)
                        groups[:] = [other for other in groups if not any(other is option for option in options)]
                        index = groups.index(group)
                        continue
            if len(options) == 1 and (minimum == 2 or sum(
                any(match_rank(draft, member, points) == 1 for member in options[0])
                for row in groups if row is not options[0] for draft in row if not station_position(draft)
            ) == 1):
                options[0].append(point)
                groups.pop(index)
            else:
                index += 1
    return groups


def diagram_order(point):
    position = station_position(point)
    if position:
        x, y = position[1]
        if position[0] == "table":
            return scope(point)[0], y, x
        endpoints = [_xy(end) for end in _geometry(point).get("dimension_endpoints", [])]
        if len(endpoints) == 2 and all(endpoints) and abs(endpoints[0][1] - endpoints[1][1]) > abs(endpoints[0][0] - endpoints[1][0]):
            return scope(point)[0], y, x
        return scope(point)[0], x, y
    return scope(point)[0], math.inf, math.inf


def assign_load_names(points, *, reserved=()):
    """Inputs carry only established original names. Allocate missing names once."""
    occupied = {name.casefold() for point in (*points, *reserved) for name in (point.get("label"), point.get("height_label")) if name}
    fields = (("label", "F"), ("height_label", "H"))

    def assign(point, missing, start, keep_zero=False):
        while True:
            suffix = str(start) if start or keep_zero else ""
            names = {field: prefix + suffix for field, prefix in missing}
            if all(name.casefold() not in occupied for name in names.values()):
                point.update(names)
                occupied.update(name.casefold() for name in names.values())
                return
            start += 1

    for point in points:
        missing = [(field, prefix) for field, prefix in fields if not point.get(field)]
        if len(missing) == 1 and (suffix := re.search(r"\d+$", point.get("label") or point.get("height_label") or "")):
            assign(point, missing, int(suffix[0]), keep_zero=True)
    multi = len(points) + len(reserved) > 1
    next_pair = 1 if multi else 0
    for point in points:
        if not point.get("label") and not point.get("height_label"):
            assign(point, fields, next_pair)
            next_pair = int(point["label"][1:] or 0) + 1
    for index, point in enumerate(points, 1):
        missing = [(field, prefix) for field, prefix in fields if not point.get(field)]
        if missing:
            assign(point, missing, index if multi else 0)
