"""Local circular-cap evidence for simplified cylindrical spring drawings.

Pixel distances only classify the printed dimension witnesses.  Nominal sizes
always come from original text, never from the image scale.
"""
from __future__ import annotations

import math


def repeated_coil_boundaries(axis, dimension, page, region=None):
    raster = page.get("diameter_raster")
    if raster is None:
        return None
    import cv2
    import numpy as np

    mask, scale = raster
    ink = mask if axis == 1 else mask.T
    a, b, cross = (round(dimension[k] * scale) for k in ("a", "b", "cross"))
    span = b - a
    if span < 40:
        return None
    for direction in (-1, 1):
        reach = []
        for endpoint in (a, b):
            guides = [g for g in dimension["guides"] if abs(g[0] * scale - endpoint) <= max(3, span * .025)]
            reach.append(max((direction * (c * scale - cross) for g in guides for c in (g[1], g[3])), default=0))
        if min(reach) < span * .12:
            continue
        # Center guides often continue through the entire view.  Inspect the
        # witnessed interval, rather than stepping beyond their farthest end.
        lo, hi = sorted((cross-direction*span*.05, cross+direction*min(max(reach)+span*1.5, span*4)))
        lo, hi = max(0, round(lo)), min(ink.shape[1], round(hi))
        groups = []
        for endpoint, side in ((a, -1), (b, 1)):
            top, bottom = max(0, round(endpoint-span*.23)), min(ink.shape[0], round(endpoint+span*.23))
            roi = ink[top:bottom, lo:hi].copy()
            if roi.size == 0:
                break
            # Dashed centerlines must not masquerade as round wire caps.
            straight = cv2.morphologyEx(roi, cv2.MORPH_OPEN, np.ones((1, max(9, round(span*.22))), np.uint8))
            curved = roi & ~straight
            circles = cv2.HoughCircles(cv2.GaussianBlur(curved, (3, 3), 0), cv2.HOUGH_GRADIENT,
                                       1, 5, param1=100, param2=8, minRadius=3, maxRadius=round(span*.14))
            caps = []
            if circles is not None:
                for x, y, radius in circles[0]:
                    cap = _fit_cap(curved, float(x), float(y), float(radius), side, span)
                    if cap is None:
                        continue
                    x, y, radius, error = cap
                    point = [0., 0.]
                    point[axis], point[1-axis] = (y+top)/scale, (x+lo)/scale
                    if region and not (region["x"] <= point[0]/page["width"] <= region["x"]+region["width"] and
                                       region["y"] <= point[1]/page["height"] <= region["y"]+region["height"]):
                        continue
                    cap = (x+lo, y+top, radius, error)
                    duplicate = next((c for c in caps if abs(c[0]-cap[0]) < max(c[2], radius)*1.2), None)
                    if duplicate:
                        if cap[3] >= duplicate[3]:
                            continue
                        caps.remove(duplicate)
                    caps.append(cap)
            group = _cap_row(caps, span)
            if group is None:
                break
            groups.append(group)
        if len(groups) != 2:
            continue
        first, second = groups
        radius = float(np.median([c[2] for row in groups for c in row]))
        if min(c[2] for row in groups for c in row) < radius*.55 or max(c[2] for row in groups for c in row) > radius*1.6:
            continue
        start, end = max(min(c[0] for c in row) for row in groups), min(max(c[0] for c in row) for row in groups)
        if end-start < radius*1.8:
            continue
        slopes, centers, guide_centers = [], [], []
        for row in groups:
            slope, intercept = np.polyfit([c[0] for c in row], [c[1] for c in row], 1)
            slopes.append(float(slope))
            guide_centers.append(float(slope*(start+end)/2+intercept))
            centers.append(float(slope*cross+intercept))
        if abs(slopes[0]-slopes[1]) > .035 or centers[1]-centers[0] < radius*5:
            continue
        if not _connecting_coil_strokes(ink, guide_centers, start, end, radius):
            continue
        # The drawing must independently contain the two wire-center guides.
        # A single spring-axis line is not enough to establish a mean diameter.
        if not all(_center_guide(page, axis, center/scale, radius/scale, start/scale, end/scale) for center in guide_centers):
            continue
        tolerance = max(1.6, radius*.35)
        choices = []
        for field, offset in (("inner_diameter", 1), ("mean_diameter", 0), ("outer_diameter", -1)):
            expected = (centers[0]+offset*radius, centers[1]-offset*radius)
            if max(abs(a-expected[0]), abs(b-expected[1])) <= tolerance:
                choices.append(field)
        if len(choices) != 1:
            continue
        return choices[0], {"method": "repeated_coil_arcs", "axis": axis,
                            "centers": [v/scale for v in centers], "radius": radius/scale,
                            "axial_extent": [min(c[0] for row in groups for c in row)/scale,
                                             max(c[0] for row in groups for c in row)/scale],
                            "caps": [[[v/scale for v in c[:3]] for c in row] for row in groups]}
    return None


def _connecting_coil_strokes(ink, centers, start, end, radius):
    """Two text rows or table circles are not a connected helical view."""
    import cv2
    import numpy as np

    a,b=centers
    top,bottom=max(0,round(a-radius)),min(ink.shape[0],round(b+radius))
    left,right=max(0,round(start-radius*2)),min(ink.shape[1],round(end+radius*2))
    region=ink[top:bottom,left:right]
    span=b-a
    if not region.size:
        return False
    lines=cv2.HoughLinesP(region,1,np.pi/180,threshold=max(12,round(span*.18)),
                          minLineLength=max(12,round(span*.65)),maxLineGap=max(3,round(radius)))
    strokes=[]
    if lines is not None:
        for x,y,xx,yy in lines.reshape(-1,4):
            if abs(yy-y) < span*.65 or abs(xx-x) < radius*1.3:
                continue
            if min(y,yy)+top > a+radius*2 or max(y,yy)+top < b-radius*2:
                continue
            midpoint=(float(x+xx)/2,float(y+yy)/2)
            if not any(abs(midpoint[0]-old[0]) < radius for old in strokes):
                strokes.append(midpoint)
    return len(strokes)>=2


def _fit_cap(mask, x, y, radius, side, span):
    import numpy as np

    left, right = max(0, round(x-radius*1.15)), min(mask.shape[1], round(x+radius*1.15)+1)
    if right-left < 6:
        return None
    points = []
    top, bottom = max(0, round(y-radius*1.3)), min(mask.shape[0], round(y+radius*1.3)+1)
    for col in range(left, right):
        rows = np.flatnonzero(mask[top:bottom, col])+top
        if len(rows):
            row = rows[0] if side < 0 else rows[-1]
            points.append((col, row))
    if len(points) < 6:
        return None
    tip = min(p[1] for p in points) if side < 0 else max(p[1] for p in points)
    points = np.array([p for p in points if side*(p[1]-tip) >= -radius*.8], dtype=float)
    if len(points) < 6:
        return None
    xx, yy = points.T
    ox, oy = xx.mean(), yy.mean()
    xx, yy = xx-ox, yy-oy
    solution, _, _, _ = np.linalg.lstsq(np.column_stack((2*xx, 2*yy, np.ones(len(xx)))), xx*xx+yy*yy, rcond=None)
    cx, cy, constant = solution
    squared = constant+cx*cx+cy*cy
    if squared <= 0:
        return None
    fitted = math.sqrt(squared)
    cx, cy = cx+ox, cy+oy
    if not 2.5 <= fitted <= span*.15 or side*(tip-cy) < fitted*.65:
        return None
    if np.ptp(points[:, 0]) < fitted*1.2 or np.ptp(points[:, 1]) < fitted*.18:
        return None
    error = float(np.mean(np.abs(np.hypot(points[:, 0]-cx, points[:, 1]-cy)-fitted)))
    if error > max(.65, fitted*.10):
        return None
    return cx, cy, fitted, error/fitted


def _cap_row(caps, span):
    import numpy as np

    best = None
    for first in caps:
        for second in caps:
            if second[0]-first[0] < max(first[2], second[2])*3:
                continue
            slope = (second[1]-first[1])/(second[0]-first[0])
            if abs(slope) > .055:
                continue
            row = sorted((c for c in caps if abs(c[1]-first[1]-slope*(c[0]-first[0])) <= max(1.3, first[2]*.12)
                          and .75*first[2] <= c[2] <= 1.4*first[2]), key=lambda c: c[0])
            if len(row) < 2:
                continue
            gaps = np.diff([c[0] for c in row])
            if min(gaps) < max(c[2] for c in row)*2.8 or max(gaps) > min(gaps)*2.2:
                continue
            if best is None or len(row) > len(best) or len(row) == len(best) and sum(c[3] for c in row) < sum(c[3] for c in best):
                best = row
    return best


def _center_guide(page, axis, center, radius, start, end):
    pieces = []
    for line in [*page["lines"], *page.get("line_segments", [])]:
        if max(abs(line[axis]-center), abs(line[axis+2]-center)) > max(radius*.38, .7):
            continue
        a, b = sorted((line[1-axis], line[3-axis]))
        if a < end and b > start:
            pieces.append((max(a, start), min(b, end)))
    covered, previous = 0, start
    for a, b in sorted(pieces):
        covered += max(0, b-max(previous, a))
        previous = max(previous, b)
    return covered >= (end-start)*.38
