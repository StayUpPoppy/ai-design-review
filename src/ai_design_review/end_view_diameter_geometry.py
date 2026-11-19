"""Match original dimension witnesses to concentric spring end-view circles.

Pixel distances establish the diameter role only. Nominal values and offsets
continue to come from the original text evidence.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import logging
import math
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

VERSION = "end-view-diameters/v1"
LOGGER = logging.getLogger(__name__)
ANGLES = np.linspace(0, 2 * np.pi, 120, endpoint=False)
DIRECTIONS = np.column_stack((np.cos(ANGLES), np.sin(ANGLES)))


def _support(ink, center, radius):
    band = max(1.5, radius * .018)
    samples = center + (radius + np.linspace(-band, band, 5)[:, None, None]) * DIRECTIONS
    pixels = np.rint(samples).astype(int)
    valid = ((pixels[..., 0] >= 0) & (pixels[..., 0] < ink.shape[1])
             & (pixels[..., 1] >= 0) & (pixels[..., 1] < ink.shape[0]))
    values = np.zeros(valid.shape, dtype=bool)
    values[valid] = ink[pixels[..., 1][valid], pixels[..., 0][valid]] != 0
    return values.any(axis=0)


def _supported(support):
    # Require broad angular evidence, including both halves of the contour.
    return support.mean() >= .68 and sum(sector.mean() >= .5 for sector in np.split(support, 8)) >= 6


def _fit_circle(points, seed):
    center, radius = np.asarray(seed[:2], dtype=float), float(seed[2])
    distances = np.linalg.norm(points - center, axis=1)
    nearby = points[np.abs(distances - radius) <= max(3, radius * .035)]
    if len(nearby) < 24:
        return None
    for _ in range(2):
        offset = nearby - center
        matrix = np.column_stack((2 * offset, np.ones(len(offset))))
        fit, _, _, _ = np.linalg.lstsq(matrix, (offset * offset).sum(axis=1), rcond=None)
        squared = fit[2] + fit[0] ** 2 + fit[1] ** 2
        if squared <= 0:
            return None
        center = center + fit[:2]
        radius = math.sqrt(squared)
        nearby = nearby[np.abs(np.linalg.norm(nearby - center, axis=1) - radius) <= max(2, radius * .02)]
        if len(nearby) < 24:
            return None
    return center, radius


def _radii(ink, center, expected):
    radii = np.arange(max(7, expected * .35), expected * 1.85, max(1, expected * .008))
    supported = [radius for radius in radii if _supported(_support(ink, center, radius))]
    groups = []
    for radius in supported:
        if groups and radius - groups[-1][-1] <= max(3, expected * .028):
            groups[-1].append(radius)
        else:
            groups.append([radius])
    return [float(np.median(group)) for group in groups]


def _witnesses_reach(axis, dimension, center, radius, scale):
    tolerance = max(2.5, radius * .035)
    for endpoint in (dimension["a"], dimension["b"]):
        # Witness coordinates are stored in the dimension's along/across frame.
        guides = [guide for guide in dimension["guides"]
                  if abs(guide[0] - endpoint) * scale <= tolerance]
        if not any(min(guide[1], guide[3]) * scale - tolerance <= center[1 - axis]
                   <= max(guide[1], guide[3]) * scale + tolerance for guide in guides):
            return False
    return True


def _detect(axis, dimension, page, region):
    mask, scale = page["diameter_raster"]
    expected = (dimension["b"] - dimension["a"]) * scale / 2
    if expected < 14:
        return [], ""
    along = (dimension["a"] + dimension["b"]) * scale / 2
    cross = dimension["cross"] * scale
    low = [along - expected * 1.9, cross - expected * 3.4]
    high = [along + expected * 1.9, cross + expected * 3.4]
    if axis == 1:
        low.reverse()
        high.reverse()
    if region:
        low = [max(low[i], region[key] * page[size] * scale)
               for i, (key, size) in enumerate((("x", "width"), ("y", "height")))]
        high = [min(high[i], (region[key] + region[extent]) * page[size] * scale)
                for i, (key, extent, size) in enumerate((("x", "width", "width"), ("y", "height", "height")))]
    x0, y0 = [max(0, math.floor(value)) for value in low]
    x1, y1 = min(mask.shape[1], math.ceil(high[0])), min(mask.shape[0], math.ceil(high[1]))
    if x1 <= x0 or y1 <= y0:
        return [], ""
    ink = mask[y0:y1, x0:x1]
    circles = cv2.HoughCircles(cv2.GaussianBlur(ink, (3, 3), 0), cv2.HOUGH_GRADIENT,
                               1, max(8, expected * .4), param1=100, param2=24,
                               minRadius=max(8, round(expected * .92)), maxRadius=math.ceil(expected * 1.08))
    if circles is None:
        return [], ""
    contours, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    points = np.concatenate(contours).reshape(-1, 2).astype(float) if contours else np.empty((0, 2))
    matches, failures = [], []
    origin = np.array([x0, y0])
    for seed in circles[0]:
        fitted = _fit_circle(points, seed)
        if fitted is None:
            continue
        local_center, radius = fitted
        center = local_center + origin
        tolerance = max(2.5, radius * .035)
        if (abs(center[axis] - along) > tolerance or abs(radius - expected) > tolerance
                or abs(center[1 - axis] - cross) < radius * 1.03):
            continue
        if not _witnesses_reach(axis, dimension, center, radius, scale):
            failures.append("端视图尺寸界线未同时对应同一圆，请核对直径类型。")
            continue
        support = _support(ink, local_center, radius)
        tangent = 0 if axis == 0 else 30
        if not _supported(support) or not support[[tangent, (tangent + 60) % 120]].all():
            continue
        radii = _radii(ink, local_center, radius)
        if len(radii) != 2 or min(abs(other - radius) for other in radii) > tolerance * 2:
            failures.append("端视图的内外圆尚未唯一确定，请核对尺寸界线对应关系。")
            continue
        inner, outer = sorted(radii)
        if outer - inner < max(5, outer * .04):
            continue
        if region and (np.any(center - outer < np.asarray(low) - tolerance)
                       or np.any(center + outer > np.asarray(high) + tolerance)):
            failures.append("端视图跨越当前规格区域，请核对直径标注的归属。")
            continue
        role = "outer_diameter" if abs(radius - outer) < abs(radius - inner) else "inner_diameter"
        if any(np.linalg.norm(center - np.asarray(prior[1]["center"]) * scale) <= tolerance * 2
               for prior in matches):
            continue
        view = {"x": float((center[0] - outer) / (page["width"] * scale)),
                "y": float((center[1] - outer) / (page["height"] * scale)),
                "width": float(2 * outer / (page["width"] * scale)),
                "height": float(2 * outer / (page["height"] * scale))}
        contacts = [[center[0] / scale, center[1] / scale] for _ in range(2)]
        for contact, side in zip(contacts, (-1, 1)):
            contact[axis] += side * radius / scale
        matches.append((role, {"method": "end_view_circles", "version": VERSION,
                              "axis": axis, "endpoints": [dimension["a"], dimension["b"]],
                              "baseline": dimension["cross"], "page_size": [page["width"], page["height"]],
                              "center": (center / scale).tolist(), "radii": [inner / scale, outer / scale],
                              "matched_radius": radius / scale, "arc_support": float(support.mean()),
                              "view_region": view, "contacts": contacts}))
    if len(matches) > 1:
        return [], "同一尺寸线附近存在多个端视图，请核对对应的圆。"
    return matches, "" if matches else next(iter(failures), "")


def end_view_boundaries(axis, dimension, page, region=None):
    """Return one verified role, or an explanation for the existing review card."""
    if page.get("diameter_raster") is None:
        return [], ""
    from .page_images import read_json, write_json

    started = perf_counter()
    identity = [VERSION, page.get("source_document_id"), page["page"], page["width"], page["height"],
                page["diameter_raster"][0].shape, axis, dimension, region]
    key = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    memory = page.setdefault("_end_view_cache", {})
    directory = page.get("end_view_cache_dir")
    path = Path(directory) / f"{key}.json" if directory and page.get("source_document_id") else None
    cached = memory.get(key) or (read_json(path) if path else {})
    hit = (cached.get("version") == VERSION and isinstance(cached.get("matches"), list)
           and isinstance(cached.get("reason"), str))
    if not hit:
        matches, reason = _detect(axis, dimension, page, region)
        cached = {"version": VERSION, "matches": matches, "reason": reason}
        if path:
            try:
                write_json(path, cached)
            except OSError:
                LOGGER.warning("End-view cache could not be saved for page %s", page["page"], exc_info=True)
    memory[key] = cached
    LOGGER.info("End-view diameter page=%s cache_hit=%s elapsed_ms=%.1f",
                page["page"], hit, (perf_counter() - started) * 1000)
    return [(role, deepcopy(evidence)) for role, evidence in cached["matches"]], cached["reason"]
