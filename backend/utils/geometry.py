"""Geometry helpers for zones, tracking and bounding boxes."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]
BBox = Tuple[float, float, float, float]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_points(points: Iterable[Sequence[float]]) -> List[List[float]]:
    """Validate and clamp a polygon expressed in 0..1 image coordinates."""
    result: List[List[float]] = []
    for point in points:
        if len(point) < 2:
            continue
        result.append([round(clamp01(float(point[0])), 5), round(clamp01(float(point[1])), 5)])
    return result


def point_in_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    """Ray casting algorithm.  Returns True when point lies inside polygon."""
    if len(polygon) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = float(polygon[i][0]), float(polygon[i][1])
        xj, yj = float(polygon[j][0]), float(polygon[j][1])
        intersects = (yi > y) != (yj > y)
        if intersects:
            denominator = (yj - yi) or 1e-9
            x_cross = (xj - xi) * (y - yi) / denominator + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def polygon_area(polygon: Sequence[Sequence[float]]) -> float:
    if len(polygon) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(polygon):
        nxt = polygon[(index + 1) % len(polygon)]
        area += float(point[0]) * float(nxt[1]) - float(nxt[0]) * float(point[1])
    return abs(area) / 2.0


def bbox_center(bbox: Sequence[float]) -> Point:
    x, y, w, h = bbox
    return (float(x) + float(w) / 2.0, float(y) + float(h) / 2.0)


def bbox_to_list(bbox: Sequence[float]) -> List[float]:
    return [round(float(value), 5) for value in bbox]


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0
