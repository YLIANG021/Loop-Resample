"""Curve fitting, parameterization, and source-spacing sampling."""

from bisect import bisect_left, bisect_right
from math import acos

from ..i18n import pgettext
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
            pgettext("A {kind} curve needs at least {minimum} points.").format(
                kind=pgettext("closed" if is_closed else "open"), minimum=minimum
            )
        )
    segment_count = len(points) if is_closed else len(points) - 1
    if any(
        (points[(index + 1) % len(points)] - points[index]).length <= 1e-12
        for index in range(segment_count)
    ):
        raise ValueError(pgettext("A curve source contains a zero-length segment."))

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
        raise ValueError(pgettext("A fitted curve segment has no measurable length."))
    if cumulative[-1] <= 1e-12:
        raise ValueError(pgettext("The fitted curve has no measurable length."))
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


def _segment_lengths(distances):
    """The span of each source segment out of a cumulative table of control distances."""
    return tuple(
        following - current
        for current, following in zip(distances, distances[1:])
    )


def _occupy_anchor_slots(slot_measures, anchor_measures, total, is_closed):
    """Hand every anchor one of the slots the global distribution already produced.

    ``slot_measures`` is the increasing measure the caller spaced its samples by, in
    whatever unit that caller works in, and ``anchor_measures`` is where each source
    point to pin sits in the same unit.  Each anchor takes the nearest still-free slot
    and both orders stay monotone, which is what keeps the pin from crossing over
    itself; every other slot keeps the coordinate the plain distribution gave it, so
    the whole difference a pin makes is the one point it stands on.  That is also why
    the spacing and smoothing axes still move the rest of the path: an anchor is a name
    for a vertex, not a wall the distribution has to restart against.

    A closed path is read from its first anchor around the loop, so a seam sitting just
    *before* the start of the index frame takes the slot beside it instead of the one
    all the way across.  An open path's two ends are not for rent: they hold the path's
    own vertices whatever the anchors ask for, which is the guarantee the allocator
    this replaced got by adding the ends to the anchor list itself.

    Returns None when there are fewer slots than anchors, leaving the caller on its
    plain distribution rather than pinning a subset of the promises.
    """
    needed = len(anchor_measures)
    if not needed:
        return None
    if is_closed:
        origin = anchor_measures[0]
        order = sorted(
            range(len(slot_measures)),
            key=lambda index: (slot_measures[index] - origin) % total,
        )
        positions = [(slot_measures[index] - origin) % total for index in order]
        wanted = [(measure - origin) % total for measure in anchor_measures]
    else:
        order = list(range(len(slot_measures)))
        if anchor_measures[0] > 0.0:
            order.pop(0)
        if anchor_measures[-1] < total:
            order.pop()
        positions = [slot_measures[index] for index in order]
        wanted = list(anchor_measures)

    count = len(positions)
    if needed > count:
        return None

    slots = []
    cursor = 0
    for index, target in enumerate(wanted):
        # Slots still unclaimed at either end set the window this one may reach.
        high = count - needed + index
        near = bisect_left(positions, target)
        choice = None
        for candidate in (near - 1, near):
            slot = min(max(candidate, cursor), high)
            distance = abs(positions[slot] - target)
            if choice is None or distance < choice[0]:
                choice = (distance, slot)
        slots.append(order[choice[1]])
        cursor = choice[1] + 1
    return tuple(slots)


def sample_catmull_rom_curve(
    curve,
    target_count,
    anchors=(),
    even=0.0,
):
    """Sample a smooth source while preserving its original segment-density profile.

    ``anchors`` are control-point indices that must keep a sample exactly on them: a UV
    seam crossing the strip is pinned this way so no rebuilt face ever straddles it.
    Each one takes the nearest slot out of the distribution below and displaces it, so
    the rest of the path stays wherever the axes put it and only the pinned point is
    held back.  A step back to the source count is left unpinned because that step
    already lands on every source vertex.

    ``even`` is one strength of the distribution axis, from equal index steps toward
    equal arc length.  Zero hands back the arithmetic below untouched, which is the
    whole reason reverting a session lands on the mesh it started from.
    """
    minimum = 3 if curve.is_closed else 2
    if target_count < minimum:
        raise ValueError(
            pgettext("A {kind} path needs at least {minimum} points.").format(
                kind=pgettext("closed" if curve.is_closed else "open"), minimum=minimum
            )
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

    pin = bool(anchors) and (
        even != 0.0
        or target_count != len(curve.control_points)
        or not valid_profile
    )

    table = curve.control_distances
    positions = (
        measure_positions(_segment_lengths(table), even)
        if valid_profile
        else None
    ) or table
    samples = []
    slot_distances = []
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
                # of whichever segment it landed in.  Weighting a segment by its length
                # instead of by one is the whole difference between spacing that
                # follows the arc and spacing that follows the source vertices.
                distance = measure_to_distance(
                    table, positions, index * positions[-1] / divisor
                )
        else:
            distance = curve.total_length * index / divisor

        slot_distances.append(distance)
        samples.append(_sample_at_distance(curve, distance))
    if not curve.is_closed:
        samples[0] = curve.control_points[0].copy()
        samples[-1] = curve.control_points[-1].copy()
    if pin:
        points = curve.control_points
        ordered = sorted(
            {index for index in anchors if 0 <= index <= len(points) - 1},
            key=lambda index: table[index],
        )
        slots = _occupy_anchor_slots(
            slot_distances,
            [table[index] for index in ordered],
            curve.total_length,
            curve.is_closed,
        )
        if slots is not None:
            for slot, index in zip(slots, ordered):
                samples[slot] = points[index].copy()
    return samples


def parameterize_boundary(vertices, is_closed, curvature_weight=DEFAULT_CURVATURE_WEIGHT):
    """Build normalized arc-length parameters, optionally weighted by turning."""
    points = [_point(vertex) for vertex in vertices]
    minimum = 3 if is_closed else 2
    if len(points) < minimum:
        raise ValueError(
            pgettext("A {kind} boundary needs at least {minimum} points.").format(
                kind=pgettext("closed" if is_closed else "open"), minimum=minimum
            )
        )

    segment_points = points + [points[0]] if is_closed else points
    segment_lengths = tuple(
        (segment_points[index + 1] - segment_points[index]).length
        for index in range(len(segment_points) - 1)
    )
    if any(length <= 1e-12 for length in segment_lengths):
        raise ValueError(pgettext("A boundary contains a zero-length segment."))

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


def sample_by_arclength(
    vertices,
    target_count,
    is_closed,
    forced_anchors=(),
):
    """Sample a polyline without moving detected corners off the source path.

    Detected turns and the seam crossings of ``forced_anchors`` each take the nearest
    slot of the even distribution below, so a corner keeps its own vertex while the
    points between corners keep the spacing this step asked for rather than an
    interval of their own.
    """
    minimum = 3 if is_closed else 2
    if target_count < minimum:
        raise ValueError(
            pgettext("A {kind} path needs at least {minimum} points.").format(
                kind=pgettext("closed" if is_closed else "open"), minimum=minimum
            )
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

    divisor = target_count if is_closed else target_count - 1
    slot_parameters = [index / divisor for index in range(target_count)]
    samples = [
        _sample_parameterized(boundary, parameter) for parameter in slot_parameters
    ]
    slots = _occupy_anchor_slots(
        slot_parameters,
        [boundary.parameters[index] for index in anchors],
        1.0,
        is_closed,
    )
    if slots is not None:
        for slot, index in zip(slots, anchors):
            samples[slot] = _point(boundary.vertices[index])
    return samples
