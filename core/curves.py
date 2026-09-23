"""Curve fitting, parameterization, and source-spacing sampling."""

from bisect import bisect_right
from math import acos

from ..shape.warp import measure_positions, measure_to_distance
from .types import BoundaryParameters, CatmullRomCurve
from .utils import _point


DEFAULT_CURVATURE_WEIGHT = 0.55
DEFAULT_FEATURE_ANGLE_THRESHOLD = 0.45
DEFAULT_CURVE_SAMPLES_PER_SEGMENT = 8


def _catmull_rom_segment(points, segment_index, factor, is_closed):
    """Evaluate one centripetal Catmull-Rom segment."""
    count = len(points)
    first = points[segment_index]
    second = points[(segment_index + 1) % count]
    if is_closed:
        previous = points[(segment_index - 1) % count]
        following = points[(segment_index + 2) % count]
    else:
        previous = (
            points[segment_index - 1]
            if segment_index > 0
            else first * 2.0 - second
        )
        following = (
            points[segment_index + 2]
            if segment_index + 2 < count
            else second * 2.0 - first
        )

    def knot_after(knot, start, end):
        return knot + max((end - start).length, 1e-12) ** 0.5

    knot0 = 0.0
    knot1 = knot_after(knot0, previous, first)
    knot2 = knot_after(knot1, first, second)
    knot3 = knot_after(knot2, second, following)
    knot = knot1 + max(0.0, min(1.0, factor)) * (knot2 - knot1)

    def blend(start, end, start_knot, end_knot):
        span = end_knot - start_knot
        if span <= 1e-12:
            return start.copy()
        return start.lerp(end, (knot - start_knot) / span)

    level1_first = blend(previous, first, knot0, knot1)
    level1_second = blend(first, second, knot1, knot2)
    level1_third = blend(second, following, knot2, knot3)

    span = knot2 - knot0
    level2_first = level1_first.lerp(
        level1_second,
        (knot - knot0) / span if span > 1e-12 else 0.0,
    )
    span = knot3 - knot1
    level2_second = level1_second.lerp(
        level1_third,
        (knot - knot1) / span if span > 1e-12 else 0.0,
    )
    span = knot2 - knot1
    return level2_first.lerp(
        level2_second,
        (knot - knot1) / span if span > 1e-12 else 0.0,
    )


def build_catmull_rom_curve(vertices, is_closed):
    """Build a smooth interpolating curve and its arc-length lookup table."""
    points = tuple(_point(vertex) for vertex in vertices)
    minimum = 3 if is_closed else 2
    if len(points) < minimum:
        raise ValueError(
            f"A {'closed' if is_closed else 'open'} curve needs at least {minimum} points."
        )
    segment_count = len(points) if is_closed else len(points) - 1
    if any(
        (points[(index + 1) % len(points)] - points[index]).length <= 1e-12
        for index in range(segment_count)
    ):
        raise ValueError("A curve source contains a zero-length segment.")

    samples_per_segment = DEFAULT_CURVE_SAMPLES_PER_SEGMENT
    lookup_points = [points[0].copy()]
    cumulative = [0.0]
    control_distances = [0.0]
    for segment_index in range(segment_count):
        for step in range(1, samples_per_segment + 1):
            point = (
                points[(segment_index + 1) % len(points)].copy()
                if step == samples_per_segment
                else _catmull_rom_segment(
                    points,
                    segment_index,
                    step / samples_per_segment,
                    is_closed,
                )
            )
            length = (point - lookup_points[-1]).length
            if length <= 1e-12:
                continue
            lookup_points.append(point)
            cumulative.append(cumulative[-1] + length)
        control_distances.append(cumulative[-1])

    if any(
        following - current <= 1e-12
        for current, following in zip(control_distances, control_distances[1:])
    ):
        raise ValueError("A fitted curve segment has no measurable length.")
    if cumulative[-1] <= 1e-12:
        raise ValueError("The fitted curve has no measurable length.")
    return CatmullRomCurve(
        control_points=points,
        is_closed=is_closed,
        control_distances=tuple(control_distances),
        lookup_points=tuple(lookup_points),
        cumulative=tuple(cumulative),
        total_length=cumulative[-1],
    )


def _sample_at_distance(curve, distance):
    """Read the fitted curve's arc-length lookup table at one distance."""
    lookup_index = min(
        max(1, bisect_right(curve.cumulative, distance)),
        len(curve.lookup_points) - 1,
    )
    first_distance = curve.cumulative[lookup_index - 1]
    second_distance = curve.cumulative[lookup_index]
    factor = (
        (distance - first_distance) / (second_distance - first_distance)
        if second_distance > first_distance
        else 0.0
    )
    return curve.lookup_points[lookup_index - 1].lerp(
        curve.lookup_points[lookup_index],
        max(0.0, min(1.0, factor)),
    )


def _interval_samples(
    anchors,
    positions,
    is_closed,
    total_length,
    target_count,
    at_anchor,
    between,
):
    """Spread ``target_count`` samples over the anchor-to-anchor intervals.

    ``positions`` is any monotone measure along the path -- arc length on a fitted
    curve, normalized parameter on a polyline -- and ``at_anchor`` / ``between`` read
    a point from the caller's own path model, so both sources share the allocation.
    """
    if is_closed:
        pairs = [
            (anchors[index], anchors[(index + 1) % len(anchors)])
            for index in range(len(anchors))
        ]
        interval_lengths = [
            (positions[end] - positions[start]) % total_length or total_length
            for start, end in pairs
        ]
        total_segments = target_count
    else:
        pairs = list(zip(anchors, anchors[1:]))
        interval_lengths = [
            positions[end] - positions[start] for start, end in pairs
        ]
        total_segments = target_count - 1

    segments = _allocate_interval_segments(interval_lengths, total_segments)
    samples = [at_anchor(anchors[0])]
    for interval_index, ((start, end), segment_count) in enumerate(
        zip(pairs, segments)
    ):
        interval_length = interval_lengths[interval_index]
        for step in range(1, segment_count + 1):
            if (
                is_closed
                and interval_index == len(pairs) - 1
                and step == segment_count
            ):
                continue
            samples.append(
                at_anchor(end)
                if step == segment_count
                else between(start, interval_length * step / segment_count)
            )
    return samples


def _segment_lengths(distances):
    """The span of each source segment out of a cumulative table of control distances."""
    return tuple(
        following - current
        for current, following in zip(distances, distances[1:])
    )


def _distance_at(curve, table, positions, measure):
    """The arc-length distance one measure falls at, re-weighted or plain.

    ``positions`` is either the curve's own control distances or a monotone
    re-weighting of them, and the two readings only agree once the measure has been
    put back where its source segment's real length says it belongs.
    """
    if positions is not table:
        measure = measure_to_distance(table, positions, measure)
    return _sample_at_distance(curve, measure)


def _pinned_samples(curve, target_count, anchors, even=0.0):
    """Sample evenly inside each anchor-to-anchor interval, pinning the anchors.

    Returns None when the target cannot hold every anchor, so the caller keeps the
    plain distribution instead of failing the step.

    ``even`` re-weights the interval allocation, and pinning is exactly where that
    is safe: a warped measure moves the divisions between anchors, never the anchors
    themselves, so a seam's rail vertex keeps the sample it was promised.
    """
    points = curve.control_points
    table = curve.control_distances
    positions = measure_positions(
        _segment_lengths(table), even, False
    ) or table
    last = len(points) - 1
    ordered = sorted(
        {index for index in anchors if 0 <= index <= last},
        key=lambda index: positions[index],
    )
    if not curve.is_closed:
        ordered = sorted(
            {0, last, *ordered}, key=lambda index: positions[index]
        )
    if not ordered:
        return None

    try:
        total = positions[-1]
        samples = _interval_samples(
            ordered,
            positions,
            curve.is_closed,
            total,
            target_count,
            at_anchor=lambda index: points[index].copy(),
            # A closed path's anchor-to-itself interval runs off the end of the
            # measure table, and reading past that end clamps onto the closing
            # point rather than coming back around, so it wraps here instead.
            between=lambda start, offset: _distance_at(
                curve,
                table,
                positions,
                (positions[start] + offset) % total
                if curve.is_closed
                else positions[start] + offset,
            ),
        )
    except ValueError:
        return None
    if len(samples) != target_count:
        return None
    return samples


def sample_catmull_rom_curve(
    curve,
    target_count,
    anchors=(),
    even=0.0,
):
    """Sample a smooth source while preserving its original segment-density profile.

    ``anchors`` are control-point indices that must keep a sample exactly on them:
    a UV seam crossing the strip is pinned this way so no rebuilt face ever
    straddles it.  A step back to the source count is left unpinned because that
    step already lands on every source vertex.

    ``even`` is one strength of the distribution axis, from equal index steps toward
    equal arc length.  Zero hands back the arithmetic below untouched, which is the
    whole reason reverting a session lands on the mesh it started from.
    """
    minimum = 3 if curve.is_closed else 2
    if target_count < minimum:
        raise ValueError(
            f"A {'closed' if curve.is_closed else 'open'} path needs at least {minimum} points."
        )

    divisor = target_count if curve.is_closed else target_count - 1
    source_segments = len(curve.control_points) if curve.is_closed else len(
        curve.control_points
    ) - 1
    valid_profile = (
        len(curve.control_distances) == source_segments + 1
        and all(
            following - current > 1e-12
            for current, following in zip(
                curve.control_distances,
                curve.control_distances[1:],
            )
        )
    )
    if not valid_profile:
        print(
            "[Loop Resample][timing] spacing-fallback "
            "mode=uniform reason=invalid-source-profile"
        )

    if anchors and (
        even != 0.0
        or target_count != len(curve.control_points)
        or not valid_profile
    ):
        pinned = _pinned_samples(
            curve, target_count, anchors, even=even
        )
        if pinned is not None:
            return pinned

    table = curve.control_distances
    positions = (
        measure_positions(_segment_lengths(table), even, True)
        if valid_profile
        else None
    ) or table
    samples = []
    for index in range(target_count):
        if valid_profile:
            if positions is table:
                source_position = index * source_segments / divisor
                source_segment = min(int(source_position), source_segments - 1)
                local_factor = source_position - source_segment
                start_distance = table[source_segment]
                end_distance = table[source_segment + 1]
                distance = start_distance + local_factor * (
                    end_distance - start_distance
                )
            else:
                # The measure is a re-scaling of the source's own index frame, so the
                # sample position is found in the measure and read back as a fraction
                # of whichever segment it landed in.  Dividing that by the segment's
                # length instead of allocating by it is the whole difference between
                # spacing that follows the source vertices and spacing that does not.
                distance = measure_to_distance(
                    table, positions, index * positions[-1] / divisor
                )
        else:
            distance = curve.total_length * index / divisor

        samples.append(_sample_at_distance(curve, distance))
    if not curve.is_closed:
        samples[0] = curve.control_points[0].copy()
        samples[-1] = curve.control_points[-1].copy()
    return samples


def parameterize_boundary(vertices, is_closed, curvature_weight=DEFAULT_CURVATURE_WEIGHT):
    """Build normalized arc-length parameters, optionally weighted by turning."""
    points = [_point(vertex) for vertex in vertices]
    minimum = 3 if is_closed else 2
    if len(points) < minimum:
        raise ValueError(
            f"A {'closed' if is_closed else 'open'} boundary needs at least {minimum} points."
        )

    segment_points = points + [points[0]] if is_closed else points
    segment_lengths = tuple(
        (segment_points[index + 1] - segment_points[index]).length
        for index in range(len(segment_points) - 1)
    )
    if any(length <= 1e-12 for length in segment_lengths):
        raise ValueError("A boundary contains a zero-length segment.")

    turn_strength = [0.0] * len(points)
    last_index = len(points) - 1
    for index in range(len(points)):
        if not is_closed and index in {0, last_index}:
            continue
        previous = index - 1 if index else last_index
        following = (index + 1) % len(points)
        incoming = (points[index] - points[previous]).normalized()
        outgoing = (points[following] - points[index]).normalized()
        turn_strength[index] = acos(max(-1.0, min(1.0, incoming.dot(outgoing))))

    metric_lengths = []
    for index, length in enumerate(segment_lengths):
        following = (index + 1) % len(points)
        turn = 0.5 * (turn_strength[index] + turn_strength[following])
        metric_lengths.append(length * (1.0 + max(0.0, curvature_weight) * turn))

    cumulative = [0.0]
    for length in metric_lengths:
        cumulative.append(cumulative[-1] + length)
    metric_total = cumulative[-1]
    vertex_distances = cumulative[:-1] if is_closed else cumulative
    parameters = tuple(value / metric_total for value in vertex_distances)
    return BoundaryParameters(
        tuple(vertices),
        is_closed,
        segment_lengths,
        tuple(metric_lengths),
        tuple(cumulative),
        parameters,
        tuple(turn_strength),
        metric_total,
    )


def _sample_parameterized(boundary, parameter):
    """Sample a parameterized boundary at normalized metric distance."""
    if boundary.is_closed:
        parameter %= 1.0
    else:
        parameter = max(0.0, min(1.0, parameter))
    distance = parameter * boundary.metric_total
    segment_index = min(
        bisect_right(boundary.cumulative, distance) - 1,
        len(boundary.metric_lengths) - 1,
    )
    traversed = boundary.cumulative[segment_index]
    metric_length = boundary.metric_lengths[segment_index]
    factor = (distance - traversed) / metric_length if metric_length > 1e-12 else 0.0
    first = _point(boundary.vertices[segment_index])
    second = _point(boundary.vertices[(segment_index + 1) % len(boundary.vertices)])
    return first.lerp(second, max(0.0, min(1.0, factor)))


def detect_feature_anchors(
    boundary,
    angle_threshold=DEFAULT_FEATURE_ANGLE_THRESHOLD,
):
    """Return stable vertex indices for endpoints and pronounced turns."""
    anchors = set()
    if not boundary.is_closed:
        anchors.update({0, len(boundary.vertices) - 1})
    for index, turn in enumerate(boundary.turn_strength):
        if turn >= angle_threshold:
            anchors.add(index)

    return tuple(sorted(anchors, key=lambda index: boundary.parameters[index]))


def _limit_feature_anchors(boundary, anchors, target_count):
    """Keep the strongest available turns when the target cannot hold every anchor."""
    if len(anchors) <= target_count:
        return tuple(anchors)

    mandatory = set()
    if not boundary.is_closed:
        mandatory.update({0, len(boundary.vertices) - 1})
    remaining_slots = target_count - len(mandatory)
    candidates = [index for index in anchors if index not in mandatory]
    strongest = sorted(
        candidates,
        key=lambda index: (boundary.turn_strength[index], -index),
        reverse=True,
    )[:remaining_slots]
    selected = mandatory | set(strongest)
    return tuple(sorted(selected, key=lambda index: boundary.parameters[index]))


def _allocate_interval_segments(interval_lengths, total_segments):
    """Allocate at least one segment to each feature-to-feature interval."""
    if total_segments < len(interval_lengths):
        raise ValueError("The target count cannot preserve every feature anchor.")

    segments = [1] * len(interval_lengths)
    remaining = total_segments - len(interval_lengths)
    if remaining == 0:
        return segments

    total_length = sum(interval_lengths)
    if total_length <= 1e-12:
        raise ValueError("Feature anchors do not span a valid boundary.")

    exact_additions = [remaining * length / total_length for length in interval_lengths]
    whole_additions = [int(value) for value in exact_additions]
    for index, amount in enumerate(whole_additions):
        segments[index] += amount

    unallocated = remaining - sum(whole_additions)
    ranked = sorted(
        range(len(interval_lengths)),
        key=lambda index: (
            exact_additions[index] - whole_additions[index],
            interval_lengths[index],
            -index,
        ),
        reverse=True,
    )
    for index in ranked[:unallocated]:
        segments[index] += 1
    return segments


def sample_by_arclength(
    vertices,
    target_count,
    is_closed,
    forced_anchors=(),
):
    """Sample a polyline without moving detected corners off the source path."""
    minimum = 3 if is_closed else 2
    if target_count < minimum:
        raise ValueError(
            f"A {'closed' if is_closed else 'open'} path needs at least {minimum} points."
        )
    boundary = parameterize_boundary(vertices, is_closed)
    anchors = detect_feature_anchors(boundary)
    if forced_anchors:
        last = len(boundary.vertices) - 1
        anchors = tuple(
            sorted(
                set(anchors) | {index for index in forced_anchors if 0 <= index <= last},
                key=lambda index: boundary.parameters[index],
            )
        )
    anchors = _limit_feature_anchors(boundary, anchors, target_count)

    if not anchors:
        divisor = target_count if is_closed else target_count - 1
        parameters = [index / divisor for index in range(target_count)]
        samples = [_sample_parameterized(boundary, parameter) for parameter in parameters]
        return samples

    samples = _interval_samples(
        anchors,
        boundary.parameters,
        is_closed,
        1.0,
        target_count,
        at_anchor=lambda index: _point(boundary.vertices[index]),
        between=lambda start, offset: _sample_parameterized(
            boundary,
            boundary.parameters[start] + offset,
        ),
    )
    if len(samples) != target_count:
        raise RuntimeError("Feature-aware sampling returned the wrong point count.")
    return samples
