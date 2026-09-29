"""Curve fitting, parameterization, and source-spacing sampling."""

from bisect import bisect_right
from math import acos

from ..i18n import pgettext
from ..shape.warp import measure_positions, measure_to_distance
from .diagnostics import enabled
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


def _allocate_stretch_gaps(stretch_spans, total_gaps):
    """At least one gap per stretch, the rest by largest remainder.

    The allocator the interval sampler used to run, read as gaps rather than samples: a
    stretch's step count follows its own span, never where the neighbouring anchors stood.
    """
    if total_gaps < len(stretch_spans):
        return None
    gaps = [1] * len(stretch_spans)
    remaining = total_gaps - len(stretch_spans)
    if remaining == 0:
        return tuple(gaps)
    total_span = sum(stretch_spans)
    if total_span <= 1e-12:
        return None
    exact = [remaining * span / total_span for span in stretch_spans]
    whole = [int(value) for value in exact]
    for index, amount in enumerate(whole):
        gaps[index] += amount
    unallocated = remaining - sum(whole)
    ranked = sorted(
        range(len(stretch_spans)),
        key=lambda index: (
            exact[index] - whole[index],
            stretch_spans[index],
            -index,
        ),
        reverse=True,
    )
    for index in ranked[:unallocated]:
        gaps[index] += 1
    return tuple(gaps)


def _anchor_slot_partition(count, anchor_measures, total, is_closed):
    """The slot each anchor stands on, with the stretches between them sized to fit.

    Which slot holds an anchor is free to choose, and the choice decides how many slots each
    anchor-to-anchor stretch gets to divide; those counts come from ``_allocate_stretch_gaps``.
    On a closed path the first anchor takes the slot nearest its own position, keeping a pinned
    step aligned with the plain distribution beside it, and the rest follow around the loop; on
    an open one the two ends bound the first and last stretches wherever the anchors did not sit
    on them.

    Returns None rather than pinning a subset when the count cannot hold every anchor.
    """
    needed = len(anchor_measures)
    if not needed:
        return None
    if is_closed:
        spans = [
            (anchor_measures[(index + 1) % needed] - anchor_measures[index]) % total
            or total
            for index in range(needed)
        ]
        gaps = _allocate_stretch_gaps(spans, count)
        if gaps is None:
            return None
        first = round(anchor_measures[0] / total * count) % count
        slots = []
        walk = first
        for gap in gaps:
            slots.append(walk % count)
            walk += gap
        return tuple(slots)
    boundaries = []
    if anchor_measures[0] > 0.0:
        boundaries.append((0.0, False))
    boundaries.extend((measure, True) for measure in anchor_measures)
    if anchor_measures[-1] < total:
        boundaries.append((total, False))
    spans = [
        boundaries[index + 1][0] - boundaries[index][0]
        for index in range(len(boundaries) - 1)
    ]
    gaps = _allocate_stretch_gaps(spans, count - 1)
    if gaps is None:
        return None
    slots = []
    if boundaries[0][1]:
        slots.append(0)
    walk = 0
    for (_, is_anchor), gap in zip(boundaries[1:], gaps):
        walk += gap
        if is_anchor:
            slots.append(walk)
    return tuple(slots)


def _spread_free_slots(count, anchor_slots, anchor_measures, total, is_closed):
    """Even frame positions for every slot no anchor stands on.

    An anchor displaces the slot it rents, handing one neighbour a short step and the other a
    long one, so the free slots between two anchors divide that stretch evenly, in the frame
    the plain distribution was even in and bounded by the anchors' positions there.  On a
    closed path the last stretch wraps around to the first anchor and a lone anchor bounds a
    stretch all the way around; on an open one the two ends bound the first and last stretches.

    Yields ``(slot, measure)``; the caller reads the sample at that measure.  ``anchor_slots``
    arrives in measure order, as ``_anchor_slot_partition`` returned it, and no two anchors
    share a slot.
    """
    pairs = list(zip(anchor_slots, anchor_measures))
    if is_closed:
        stretches = []
        for index in range(len(pairs)):
            start_slot, start_measure = pairs[index]
            end_slot, end_measure = pairs[(index + 1) % len(pairs)]
            span = (end_measure - start_measure) % total or total
            stretches.append((start_slot, end_slot, start_measure, span))
    else:
        bounds = list(pairs)
        if bounds[0][0] != 0:
            bounds.insert(0, (0, 0.0))
        if bounds[-1][0] != count - 1:
            bounds.append((count - 1, total))
        stretches = [
            (
                bounds[index][0],
                bounds[index + 1][0],
                bounds[index][1],
                bounds[index + 1][1] - bounds[index][1],
            )
            for index in range(len(bounds) - 1)
        ]
    for start_slot, end_slot, start_measure, span in stretches:
        free = (
            (end_slot - start_slot - 1) % count
            if is_closed
            else end_slot - start_slot - 1
        )
        if free <= 0 or span <= 0.0:
            continue
        for step in range(1, free + 1):
            measure = start_measure + span * step / (free + 1)
            yield (
                (start_slot + step) % count if is_closed else start_slot + step,
                measure % total if is_closed else measure,
            )


def sample_catmull_rom_curve(
    curve,
    target_count,
    anchors=(),
    even=0.0,
):
    """Sample a smooth source while preserving its original segment-density profile.

    ``anchors`` are control-point indices that must keep a sample exactly on them: a UV seam
    crossing the strip is pinned this way so no rebuilt face ever straddles it.  Slot choice
    goes to ``_anchor_slot_partition`` and ``_spread_free_slots``.  A step back to the source
    count is left unpinned because it already lands on every source vertex.

    ``even`` is one strength of the distribution axis, from equal index steps toward equal arc
    length.  Zero hands back the index-frame arithmetic below untouched on an unpinned path.  A
    pinned path spaces evenly on the measure instead: the pin has already moved the slot that
    would have kept the profile's promise to the source vertices.

    ``landing`` maps each pinned source point to the slot holding it.  Only ``.seams`` reads
    it, to report which crossings the slots could not hold, since a refused pin is otherwise
    indistinguishable from one that held.  ``None`` means the identity step, so slot ``k``
    still holds source point ``k``.  An empty mapping means nothing is pinned: either the rail
    had too few rentable slots, so every sample stays on the plain distribution, or no anchor
    was asked for.
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
    if not valid_profile and enabled():
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
    # ``positions`` may be the measure table standing in for the arc, and the branch below
    # reads back what it was handed, so ``even == 0`` keeps the index-frame arithmetic exact.
    follow_source = valid_profile and positions is table and not pin
    samples = []
    for index in range(target_count):
        if valid_profile:
            if follow_source:
                source_position = index * source_segments / divisor
                source_segment = min(int(source_position), source_segments - 1)
                local_factor = source_position - source_segment
                start_distance = table[source_segment]
                end_distance = table[source_segment + 1]
                distance = start_distance + local_factor * (
                    end_distance - start_distance
                )
            else:
                # The measure re-scales the source's own index frame: the position is
                # found in it and read back as a fraction of the segment it landed in.
                # Weighting a segment by its length instead of by one is what separates
                # arc spacing from spacing that follows the source vertices.
                distance = measure_to_distance(
                    table, positions, index * positions[-1] / divisor
                )
        else:
            distance = curve.total_length * index / divisor

        samples.append(_sample_at_distance(curve, distance))
    if not curve.is_closed:
        samples[0] = curve.control_points[0].copy()
        samples[-1] = curve.control_points[-1].copy()
    landing = (
        None
        if valid_profile
        and positions is table
        and target_count == len(curve.control_points)
        else {}
    )
    if pin:
        points = curve.control_points
        ordered = sorted(
            {index for index in anchors if 0 <= index <= len(points) - 1},
            key=lambda index: table[index],
        )
        slots = _anchor_slot_partition(
            target_count,
            [positions[index] for index in ordered],
            positions[-1],
            curve.is_closed,
        )
        if slots is not None:
            for slot, index in zip(slots, ordered):
                samples[slot] = points[index].copy()
            if valid_profile:
                # Read the free slots back onto the arc through the same measure the
                # unpinned branch used.
                for slot, measure in _spread_free_slots(
                    target_count,
                    slots,
                    [positions[index] for index in ordered],
                    positions[-1],
                    curve.is_closed,
                ):
                    samples[slot] = _sample_at_distance(
                        curve,
                        measure_to_distance(table, positions, measure),
                    )
        landing = dict(zip(ordered, slots)) if slots is not None else {}
    return samples, landing


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

    Detected turns and the seam crossings of ``forced_anchors`` each hold their own vertex, and
    the stretches between them are sized by span.  ``(samples, landing)`` carries the meaning
    the curve sampler gives it, but this fallback has no identity case: its slots are even in
    the *weighted* parameter, so only the table says where a held corner ended up.
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
    slots = _anchor_slot_partition(
        target_count,
        [boundary.parameters[index] for index in anchors],
        1.0,
        is_closed,
    )
    if slots is not None:
        for slot, index in zip(slots, anchors):
            samples[slot] = _point(boundary.vertices[index])
        for slot, measure in _spread_free_slots(
            target_count,
            slots,
            [boundary.parameters[index] for index in anchors],
            1.0,
            is_closed,
        ):
            samples[slot] = _sample_parameterized(boundary, measure)
    return samples, dict(zip(anchors, slots)) if slots is not None else {}
