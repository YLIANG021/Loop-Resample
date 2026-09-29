"""Taubin low-pass: relax a path's control points without letting it shrink.

A plain Laplacian pass smooths by shrinking, and a resample that quietly shortens the
user's loop reads as a bug.  Taubin alternates over- and under-relaxing to avoid that.
The pass count has no exact right value, which is why the smoothing axis runs one way
only.
"""

LAMBDA = 0.5
MU = -0.53
ITERATIONS = 4

# Two neighbours moving at each other by a quarter of the shorter of their own segments
# still leaves half that segment, above the length the curve fit refuses.  The cap is
# measured on the frozen source polish starts from (smoothing is the only thing that
# moves a path), so a full-strength pass still takes a refitted curve.
DISPLACEMENT_CAP = 0.25


def polish_points(points, closed, strength):
    """Move every control point ``strength`` of the way toward its Taubin result."""
    smoothed = points
    for _ in range(ITERATIONS):
        smoothed = _relax(smoothed, closed, LAMBDA)
        smoothed = _relax(smoothed, closed, MU)

    count = len(points)
    moved = []
    for index, (start, target) in enumerate(zip(points, smoothed)):
        if not closed and index in (0, count - 1):
            moved.append(start.copy())
            continue
        offset = (target - start) * strength
        limit = DISPLACEMENT_CAP * _shortest_neighbour(points, index, closed)
        length = offset.length
        if limit > 0.0 and length > limit:
            offset = offset * (limit / length)
        moved.append(start + offset)
    return moved


def _relax(points, closed, factor):
    """One ``p + factor * (mean(neighbours) - p)`` pass over the path."""
    count = len(points)
    moved = []
    for index, point in enumerate(points):
        if not closed and index in (0, count - 1):
            moved.append(point.copy())
            continue
        mean = (points[index - 1] + points[(index + 1) % count]) * 0.5
        moved.append(point + (mean - point) * factor)
    return moved


def _shortest_neighbour(points, index, closed):
    """The shorter of the two segments meeting at one control point."""
    count = len(points)
    lengths = []
    if index > 0 or closed:
        lengths.append((points[index] - points[index - 1]).length)
    if index < count - 1 or closed:
        lengths.append((points[(index + 1) % count] - points[index]).length)
    return min(lengths) if lengths else 0.0
