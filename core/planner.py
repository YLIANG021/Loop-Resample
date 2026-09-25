"""Ordered strip planner.

The operation is intentionally narrow: two ordered curves are connected by a
monotone ladder. Planning and face construction use the same transitions, so
the final mesh cannot change a local connection after it has been searched.
"""

import math
import time

from ..i18n import pgettext
from .curves import _sample_parameterized, parameterize_boundary
from .diagnostics import (
    accumulate_scan,
    print_ladder_dp,
    print_ladder_plan,
    print_outer_replay,
    print_outer_align,
    print_outer_rungs,
    print_pairing_profile,
    print_reflex_fallback,
    print_seam_crossing_skipped,
)
from .geometry import (
    _crossing_after_box_overlap,
    _segments_intersect,
    diagnose_ordered_strip_geometry,
    face_quality_cost,
    validate_ordered_strip_plan,
    wide_face_reflex_metrics,
)
from .types import TRANSITION_ADVANCE, StripPlan
from .utils import _point, _point_view

RUNG_CONTINUITY_VECTOR_WEIGHT = 0.75
TRIANGLE_DISTRIBUTION_WEIGHT = 0.9
RUNG_LENGTH_WEIGHT = 1.2
# A two-column face whose corner turns against its own winding re-enters -- an
# interior angle past 180 degrees, the kite a dense rail grows when it bends toward
# the sparse rail across the span.  The sine noise floor sits near 1e-8 on a
# straight rail, so anything past 1e-6 is a real re-entrant corner, and the search
# refuses the step outright (a degraded sweep, see _search_ladder, prices it with
# REFLEX_PENALTY_WEIGHT instead when refusing leaves no path at all).
REFLEX_SIN_EPSILON = 1e-6
# What one point of re-entrance costs in the degraded sweep.  A refused reflex has
# no price at all; this one has to tower over every legitimate term -- the whole
# truncated shape budget is 0.75 * 50 -- so a reflex face is bought only when the
# sweep literally finds nothing else.
REFLEX_PENALTY_WEIGHT = 40.0
# What a two-column face pays for its worst corner, squared: the largest |cosine| of
# an interior angle, zero for a rectangle and toward one as a corner spikes or runs
# straight -- the two corners every long diagonal kite shows.  Edge ratios cannot
# tell that kite from the plain elongated quads a 9-on-19 band is full of (the
# measured saving for removing one was 0.75, nowhere near the soft face-count bid),
# but its angles give it away: ~30 degrees at the sparse vertex, ~165 at the
# skipped column.  Squared, so a slightly off-square wide on otherwise clean rails
# -- the kind a pinned count is worth keeping for -- pays almost nothing while the
# kite pays in full.  Raise it if kites still outbid the face they save; lower it
# if honest wide faces start losing to the triangles they replace.
WIDE_ANGLE_WEIGHT = 8.0
# What one face over the source band's count costs.  The count used to be a hard
# pin: the sweep was forced to buy every wide face the budget named, however ugly
# the kite -- so a 9-on-19 band pinned at 15 faces grew four long diagonal kites
# where its geometry wanted clean short spokes.  Now the count is a bid: a final
# short of the budget pays this per missing wide face, and the geometry decides
# whether the wide is worth its kite.  Raise it if rebuilt bands drift off the
# source's count too easily; lower it if kites still win where they should not.
FACE_COUNT_SOFT_WEIGHT = 2.0
# What burning one surplus step more (or fewer) than the band's own pattern had burned by
# this column costs, squared -- so a strip that dumped eight spokes on its first column when
# the source stacked four on its fourth pays at every column after it: 0.15 a step, a run of
# seven columns wrong by three pays 1.35 each.  That is the intended order: the band says how
# many spokes leave each of its columns, the rails settle where the pattern's slack lands.
# Raise it if a fan still refuses to move; lower it if rungs start stretching to pay for a
# pattern the geometry does not want.
PAIRING_TARGET_WEIGHT = 0.15
# What it costs to double a spoke on a column the source band did not double.  The
# cumulative profile prices how many surplus steps stand where; this prices which
# column each doubled spoke sits on, and it only exists when the source doubled at
# least one column -- otherwise every path doubles the same fixed number of columns
# and the charge would be a constant that settles nothing.
PINCH_PLACE_WEIGHT = 0.5
# Where a region keeps the ladder nodes its own source band named, recorded once per step
# beside the outer order they were counted in.  The solve reads them, and only to price a
# step -- see :func:`_pairing_profile`.  Nothing else writes.
_PAIRING_NODES = "pairing_nodes"


def _rail_shift(kind):
    """Which way one step moves the ladder's ``d = outer - inner``, in columns.

    The band's length difference is only ever closed by steps that shift ``d``, and the
    search's pruning assumes they all shift it the same way, so that assumption is read
    off here rather than written as a kind name.
    """
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    return outer_step - inner_step


# Temporary: how a shape axis moved a strip's connectivity.  Off costs nothing but the
# branch; nothing below reads it to decide anything.
DIAGNOSE_LADDER = True


def _triangle_distribution_cost(
    kind,
    inner_index,
    outer_index,
    next_inner,
    next_outer,
    inner_steps,
    outer_steps,
    triangle_count=0,
):
    """Prefer the strip's surplus steps at evenly spaced positions.

    A strip spends ``abs(inner_steps - outer_steps)`` steps that shift ``d`` whatever the
    search does -- a spoke or a face spanning two columns of the denser rail both move it
    one column over -- so the k-th one is pulled to k/(count+1) of the strip's length.
    Counting over the whole strip rather than over a piece of it is what lets a triangle
    sit on either side of the column a seam happened to take.

    Only steps that close the length gap are in that count, so a step which opens one --
    the pinch a band's own pairing bought it (:func:`_pairing_pinches`) -- is not spread
    against it.  No strip has ever had one of those, which is why the test is free.
    """
    shift = _rail_shift(kind)
    if not shift or triangle_count <= 0:
        return 0.0
    if shift * (outer_steps - inner_steps) < 0:
        return 0.0
    triangle_index = abs(outer_index - inner_index) + 1
    start_progress = (
        inner_index / max(inner_steps, 1)
        + outer_index / max(outer_steps, 1)
    ) * 0.5
    end_progress = (
        next_inner / max(inner_steps, 1)
        + next_outer / max(outer_steps, 1)
    ) * 0.5
    actual_progress = (start_progress + end_progress) * 0.5
    target_progress = triangle_index / (triangle_count + 1.0)
    return TRIANGLE_DISTRIBUTION_WEIGHT * (
        actual_progress - target_progress
    ) ** 2


RUNG_CONTINUITY_LENGTH_WEIGHT = 0.25


def _previous_node(kind, inner_index, outer_index):
    """Where the step that arrived at this node started, or None for the strip's own start."""
    advance = TRANSITION_ADVANCE.get(kind)
    if advance is None:
        return None
    return inner_index - advance[0], outer_index - advance[1]


def _rung_vector(boundary_geometry, inner_index, outer_index, cache=None):
    if cache is not None:
        key = (inner_index, outer_index)
        vector = cache.get(key)
        if vector is not None:
            return vector
    inner = boundary_geometry.inner_points[
        inner_index % len(boundary_geometry.inner_points)
    ]
    outer = boundary_geometry.outer_points[
        outer_index % len(boundary_geometry.outer_points)
    ]
    vector = outer - inner
    if cache is not None:
        # Callers only ever read these -- subtraction and length leave the operands
        # alone -- so one vector per node is safe to hand out repeatedly.
        cache[key] = vector
    return vector


def _rung_continuity_cost(
    boundary_geometry,
    previous_kind,
    inner_index,
    outer_index,
    next_inner,
    next_outer,
    vector_cache=None,
):
    """Penalize sudden second-order changes in rung direction and width."""
    previous_node = _previous_node(previous_kind, inner_index, outer_index)
    if previous_node is None:
        return 0.0

    previous_inner, previous_outer = previous_node
    previous_vector = _rung_vector(
        boundary_geometry,
        previous_inner,
        previous_outer,
        vector_cache,
    )
    current_vector = _rung_vector(
        boundary_geometry,
        inner_index,
        outer_index,
        vector_cache,
    )
    next_vector = _rung_vector(
        boundary_geometry,
        next_inner,
        next_outer,
        vector_cache,
    )
    scale = max(boundary_geometry.boundary_scale, 1e-12)
    vector_acceleration = (
        next_vector - current_vector * 2.0 + previous_vector
    ).length / scale
    previous_length = previous_vector.length
    current_length = current_vector.length
    next_length = next_vector.length
    length_acceleration = abs(
        next_length - 2.0 * current_length + previous_length
    ) / scale
    return (
        RUNG_CONTINUITY_VECTOR_WEIGHT * min(vector_acceleration, 4.0) ** 2
        + RUNG_CONTINUITY_LENGTH_WEIGHT * min(length_acceleration, 4.0) ** 2
    )


def _pairing_cost(inner_vertices, outer_vertices, is_closed):
    """Squared distance from every inner vertex to the outer rail read at its arc length.

    This is a qualitative measure and nothing more: a band that is nearly symmetric
    scores within a few percent for both walk directions, so it cannot pick a pairing.
    It is used to split a tie the source band's own rungs left standing, which is the
    most it has ever been trusted with.
    """
    inner = parameterize_boundary(inner_vertices, is_closed)
    outer = parameterize_boundary(outer_vertices, is_closed)
    return sum(
        (_point(vertex) - _sample_parameterized(outer, parameter)).length_squared
        for vertex, parameter in zip(inner.vertices, inner.parameters)
    )


def _rotate_nearest(vertices, point):
    if not vertices:
        return [], 0
    start = min(
        range(len(vertices)),
        key=lambda index: (_point(vertices[index]) - point).length_squared,
    )
    return vertices[start:] + vertices[:start], start


def _rail_fractions(points, is_closed):
    """Every vertex's place along its own rail, as a fraction of that rail's length.

    An index says how many vertices into a rail something sits, which stops meaning
    anything as soon as the rail is resampled; a fraction says how far around it sits,
    and a resampled rail is the same curve, so the two agree where an index cannot.
    """
    count = len(points)
    spans = count if is_closed else count - 1
    if spans < 1:
        return ()
    cumulative = [0.0]
    for index in range(spans):
        following = points[index + 1] if index + 1 < count else points[0]
        length = (following - points[index]).length
        if length <= 1e-12:
            return ()
        cumulative.append(cumulative[-1] + length)
    total = cumulative[-1]
    return tuple(value / total for value in cumulative[:count])


def _rail_columns(source_fractions, rail_fractions):
    """Which vertex of the rail being built stands where each source vertex stood.

    Both lists ascend from their rail's own first vertex, so one forward walk answers
    every source vertex at once.
    """
    columns = []
    position = 0
    last = len(rail_fractions) - 1
    for fraction in source_fractions:
        while (
            position < last
            and abs(rail_fractions[position + 1] - fraction)
            <= abs(rail_fractions[position] - fraction)
        ):
            position += 1
        columns.append(position)
    return columns


def _paired_columns(source_points, rail_vertices, is_closed, align_start=False):
    """One entry per source rail vertex: the column of the rail being built under it.

    Empty when either rail cannot be measured, which is the caller's cue to say nothing
    about the pairing rather than to name columns by a fraction it never read.

    Both fraction walks start at their own rail's first vertex, which only pairs points
    that stand in the same place when the two starts do.  An open rail's start is the
    shared endpoint, but a closed rail being built starts wherever the sampler's anchor
    put it -- the seam's pinned vertex, not the source rail's first -- so with
    ``align_start`` the two starts are registered by position first: the built vertex
    standing where the source's first vertex stood becomes the walk's origin, and the
    columns still come out in the built rail's own numbering.  Callers whose later
    transform already carries the start difference -- the outer rail's orientation and
    rotation -- leave it off; the inner rail has no such transform, and without the
    registration every column it names sits the anchor's shift away from the point it
    means.
    """
    if not source_points or len(rail_vertices) < 2:
        return ()
    source_fractions = _rail_fractions(tuple(source_points), is_closed)
    rail_points = [_point_view(vertex) for vertex in rail_vertices]
    rail_fractions = _rail_fractions(rail_points, is_closed)
    if not source_fractions or not rail_fractions:
        return ()
    if is_closed and align_start:
        start = min(
            range(len(rail_points)),
            key=lambda index: (rail_points[index] - source_points[0]).length_squared,
        )
        count = len(rail_points)
        offset = rail_fractions[start]
        rail_fractions = tuple(
            (rail_fractions[(start + step) % count] - offset) % 1.0
            for step in range(count)
        )
        return tuple(
            (start + column) % count
            for column in _rail_columns(source_fractions, rail_fractions)
        )
    return _rail_columns(source_fractions, rail_fractions)


def _rungs_on_rail(region, outer_vertices, is_closed):
    """The captured pairing counted the way the rail being built numbers itself.

    ``source_rungs`` was read off the band as the user drew it, so its outer numbers name
    the *source* rail's vertices, while the rail handed to the aligner has already been
    resampled to the count asked for now.  Folding a source number into a shorter rail
    does not name nothing, it names the wrong vertex: the rung one short of a 32-gon's
    start is the rung one short of this rail's start, and taken as an index it lands a
    third of the way around instead.  A rail is moved across by how far around it each
    rung sits, which is why the two rails' lengths are measured here.
    """
    rungs = (region or {}).get("source_rungs") or ()
    points = ((region or {}).get("frames") or {}).get("outer", {}).get("points") or ()
    if not rungs or len(outer_vertices) < 2:
        return rungs
    columns = _paired_columns(points, outer_vertices, is_closed)
    if not columns:
        return rungs
    return tuple((inner, columns[outer]) for inner, outer in rungs)


def _rungs_on_inner_rail(region, inner_vertices, rungs, is_closed):
    """The captured pairing with its inner numbers carried onto the rail being built.

    :func:`_rungs_on_rail` carries the outer numbers; the inner side still names the
    source rail's vertices.  A closed inner rail is resampled starting at the seam's
    anchor rather than at the source rail's first vertex, so its columns sit the
    anchor's shift away from the source's numbers -- and a decision ranked against
    those numbers registers the outer rail to a frame the ladder never walks, which
    leaves the pairing's pattern that many columns off the place the source band drew
    it.  Carrying the inner side across the same way is what lines the decision, the
    pairing notes and the ladder up on one frame.
    """
    points = ((region or {}).get("frames") or {}).get("inner", {}).get("points") or ()
    if not rungs or len(inner_vertices) < 2:
        return rungs
    columns = _paired_columns(
        points, inner_vertices, is_closed, align_start=True
    )
    if not columns:
        return rungs
    return tuple((columns[inner], outer) for inner, outer in rungs)


def _source_pairing_nodes(region, inner_vertices, outer_vertices, decision, is_closed):
    """The source band's own rungs, as ladder nodes.

    :func:`align_outer_boundary` already reads these pairs, and all it asks them is which
    way to walk the outer rail and where to cut it.  What it never asks is where the
    rebuilt band's rungs should sit, so a strip whose rails differ by twelve columns spends
    those twelve one-column steps wherever the local costs happen to leave them -- on the
    band this was written for, nine spokes off a single inner vertex, twice a healthy rung's
    length, where the source drew one rung and three faces two columns wide.

    The nodes are what :func:`_pairing_profile` counts into that per-column tally, which is
    to say they price a step rather than forbid one: a band rebuilt onto fewer inner columns
    than the source drew can never stand on the recorded nodes at the face count the source
    drew, but it can still be told how many of its own spokes were meant to leave each
    column, and that tally it can hit exactly.

    Each rail's numbers are carried across by arc length, because a rung names a *place* on
    a rail and both rails here have been resampled since the record was read.  The inner
    carry registers the two rails' starts first (:func:`_paired_columns` with
    ``align_start``): a closed inner rail begins at the seam's anchor, not at the source
    rail's first vertex, and without the registration every column named here sits the
    anchor's shift away from the point it means.  The outer side needs no such help --
    the walk order is the one ``decision`` chose, applied the way
    :func:`apply_outer_decision` applies it: a node named in a numbering the rail is not
    walked in blames the wrong vertex by exactly the rotation that hid it.
    """
    rungs = (region or {}).get("source_rungs") or ()
    frames = (region or {}).get("frames") or {}
    if not rungs or decision is None:
        return ()
    inner_columns = _paired_columns(
        (frames.get("inner") or {}).get("points") or (),
        inner_vertices,
        is_closed,
        align_start=True,
    )
    outer_columns = _paired_columns(
        (frames.get("outer") or {}).get("points") or (), outer_vertices, is_closed
    )
    if not inner_columns or not outer_columns:
        return ()
    orientation, rotate = decision
    outer_count = len(outer_vertices)
    nodes = set()
    for inner_index, outer_index in rungs:
        if not 0 <= inner_index < len(inner_columns):
            continue
        if not 0 <= outer_index < len(outer_columns):
            continue
        place = outer_columns[outer_index]
        if orientation:
            place = outer_count - 1 - place
        if is_closed and rotate:
            place = (place - rotate) % outer_count
        nodes.add((inner_columns[inner_index], place))
    return tuple(sorted(nodes))


def _continued(place, anchor, span):
    """The copy of ``place`` that carries on from where the walk stood last column.

    A closed band's ladder goes once around the ring, so its outer index runs past the
    rail's own last vertex and picks up at the first again.  Folding that advance back
    into ``0..span-1`` reads as a step backwards, and steps backwards are exactly what
    the ranking counts, so a rung is compared with the rung before it instead.
    """
    return place + ((anchor - place + span // 2) // span) * span


def _column_arc(places, span, is_closed):
    """One column's rungs as the short arc they sit on: where it starts, the rest's offsets.

    Two rungs leave one vertex and land next to each other on the other rail, so they
    belong a step apart -- except where the rail's own cut falls between them, which makes
    the pair read as the long way around instead.  Taken that way the column looks as
    though it spans the ring, and nothing advances across a whole ring, so the ranking
    refuses a pairing the source band uses happily and buys the advance back by rotating
    the rail off the vertex it starts at -- which is a whole row of faces sheared by one
    column.  An open rail has no cut for anything to fall between, so its places stand
    exactly as counted.
    """
    ordered = sorted(places)
    if len(ordered) < 2 or not is_closed:
        return ordered[0], tuple(place - ordered[0] for place in ordered)
    gaps = [
        (ordered[index + 1] - ordered[index], index)
        for index in range(len(ordered) - 1)
    ]
    gaps.append((ordered[0] + span - ordered[-1], len(ordered) - 1))
    _, widest = max(gaps)
    arc = [
        ordered[(widest + 1 + offset) % len(ordered)]
        for offset in range(len(ordered))
    ]
    offsets = [0]
    for index in range(len(arc) - 1):
        offsets.append(offsets[-1] + (arc[index + 1] - arc[index]) % span)
    return arc[0], tuple(offsets)


def _rung_ranking(rungs, outer_count, is_closed):
    """Every ``(orientation, rotate)`` ranked by how many source rungs it contradicts.

    Under a decision the outer rail is walked as ``j -> (walked(j) - rotate) % M``, with
    ``walked`` the identity for a forward walk and the mirror for a reversed one, and a
    ladder that only ever advances realizes those rungs only as a sequence that never
    steps back.  Counting the columns where it does is a structural verdict on the
    decision rather than a distance opinion, and it is kept on an unwrapped ring: both the
    rail's own cut and each column's own spread are read as arcs, so what the count can see
    is a band turning around, not where the rail happens to start.

    The count cannot see a shift that moves every rung along the ring by the same amount,
    because such a shift leaves the sequence just as monotone, and that shift is the
    pairing's phase.  ``head`` asks how far the first rung sits from the cut, which finds a
    phase the source band really uses; ``shift`` then prefers the rail that stays where it
    was numbered, so a band whose diagonals merely lean the other way is not answered by
    sliding a whole row off the vertex above it.  What still ties after both is left to
    :func:`_pairing_cost`, which is the measure that asks the two rails to stand opposite
    each other.
    """
    if not rungs or outer_count < 2:
        return []
    grouped = {}
    for inner_index, outer_index in rungs:
        grouped.setdefault(inner_index, []).append(outer_index)
    columns = sorted(grouped)
    ranking = []
    for orientation in (0, 1):
        arcs = [
            _column_arc(
                [
                    outer_index
                    if orientation == 0
                    else outer_count - 1 - outer_index
                    for outer_index in grouped[inner_index]
                ],
                outer_count,
                is_closed,
            )
            for inner_index in columns
        ]
        rotations = range(outer_count) if is_closed else (0,)
        for rotate in rotations:
            highest = -1
            conflicts = 0
            head = 0
            anchor = None
            for position, (base, offsets) in enumerate(arcs):
                start = (base - rotate) % outer_count if is_closed else base
                if anchor is not None:
                    start = _continued(start, anchor, outer_count)
                places = [start + offset for offset in offsets]
                lowest = min(places)
                if anchor is not None and lowest < highest:
                    conflicts += 1
                highest = max(highest, max(places))
                if not position:
                    head = (
                        min(
                            min(place % outer_count, outer_count - place % outer_count)
                            for place in places
                        )
                        if is_closed
                        else lowest
                    )
                anchor = lowest
            ranking.append(
                (
                    (
                        conflicts,
                        head,
                        min(rotate, outer_count - rotate) if is_closed else 0,
                    ),
                    (orientation, rotate),
                )
            )
    return ranking


def _rung_decision(inner_vertices, outer_vertices, rungs, is_closed):
    """The pairing the band's own rungs ask for, or None where they ask for nothing.

    Returns ``(decision, rank, tied)``; ``tied`` is how many decisions share the winning
    rank, which is how often the arc-length measure still got a vote.
    """
    ranking = _rung_ranking(rungs, len(outer_vertices), is_closed)
    if not ranking:
        return None
    key = min(rank for rank, _ in ranking)
    tied = [decision for rank, decision in ranking if rank == key]
    width = len(tied)
    if width > 1:
        tied = [
            min(
                tied,
                key=lambda decision: _pairing_cost(
                    inner_vertices,
                    apply_outer_decision(outer_vertices, decision, is_closed),
                    is_closed,
                ),
            )
        ]
    return tied[0], key, width


def align_outer_boundary(inner_vertices, outer_vertices, is_closed, region=None):
    """Choose one orientation and, for a loop, one rotation, and report which.

    The decision is the pair ``(orientation_index, rotate)`` rather than the reordered
    vertices, because :func:`ladder_steps` freezes it alongside the ladder that was
    solved on top of it: a saved sequence of transitions is a run of advances over
    *this* order's indices, so replaying it only means anything once the order that
    made it is replayed as well.

    The rung structure captured from the source band decides, because it is the pairing
    the user drew rather than a reading of it; the arc-length measure only ranks the two
    orientations for a region whose band offers no rungs, which is the case it was
    originally asked to cover.
    """
    outer = list(outer_vertices)
    rungs = _rungs_on_rail(region, outer, is_closed)
    rungs = _rungs_on_inner_rail(region, inner_vertices, rungs, is_closed)
    decided = _rung_decision(inner_vertices, outer, rungs, is_closed)
    if decided is not None:
        decision, rank, tied = decided
        if DIAGNOSE_LADDER and region is not None:
            print_outer_rungs(
                region, rungs, rank, tied, decision, is_closed
            )
        return apply_outer_decision(outer, decision, is_closed), decision
    inner_start = _point(inner_vertices[0])
    candidates = []
    decisions = []
    for orientation_index, orientation in enumerate((outer, list(reversed(outer)))):
        candidate, rotate = (
            _rotate_nearest(orientation, inner_start)
            if is_closed
            else (orientation, 0)
        )
        candidates.append(
            (_pairing_cost(inner_vertices, candidate, is_closed), candidate)
        )
        decisions.append((orientation_index, rotate))
    chosen_index = min(
        range(len(candidates)), key=lambda index: candidates[index][0]
    )
    if DIAGNOSE_LADDER and region is not None:
        print_outer_align(
            region, candidates, chosen_index, decisions[chosen_index][1], is_closed
        )
    return candidates[chosen_index][1], decisions[chosen_index]


def apply_outer_decision(outer_vertices, decision, is_closed):
    """Walk the outer rail the way a frozen decision chose to walk it.

    The rotation is replayed as the index it picked, not re-derived from where the
    rail sits now: re-deriving it would let one shape tick slide every rung of a band
    along it at once, which is a far larger connectivity change than the search
    refusing one rung.
    """
    orientation = (
        list(outer_vertices) if decision[0] == 0 else list(reversed(outer_vertices))
    )
    if is_closed and decision[1]:
        orientation = orientation[decision[1]:] + orientation[:decision[1]]
    return orientation


def _transition_face(inner, outer, inner_index, outer_index, kind):
    """The corners of one step, wound the way the quad that starts there is wound."""
    inner_count = len(inner)
    outer_count = len(outer)
    current_inner = inner[inner_index % inner_count]
    current_outer = outer[outer_index % outer_count]
    if kind == "QUAD":
        return (
            current_inner,
            inner[(inner_index + 1) % inner_count],
            outer[(outer_index + 1) % outer_count],
            current_outer,
        )
    if kind == "INNER_TRI":
        return (
            current_inner,
            inner[(inner_index + 1) % inner_count],
            current_outer,
        )
    if kind == "OUTER_WIDE":
        return (
            current_inner,
            outer[(outer_index + 2) % outer_count],
            outer[(outer_index + 1) % outer_count],
            current_outer,
        )
    if kind == "INNER_WIDE":
        return (
            current_inner,
            inner[(inner_index + 1) % inner_count],
            inner[(inner_index + 2) % inner_count],
            current_outer,
        )
    return (
        current_inner,
        outer[(outer_index + 1) % outer_count],
        current_outer,
    )


def _advance(kind, inner_index, outer_index):
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    return inner_index + inner_step, outer_index + outer_step


def _pairing_pinches(nodes, inner_steps, outer_steps):
    """How many of this band's own spokes sit on a column its rail has already left.

    A rung is one pair of columns, so walking the band's recorded rungs in the order the
    outer rail meets them gives a sequence of ``d = outer - inner`` offsets.  Every step the
    ladder takes moves ``d`` by at most one column, and only the kinds that spend the
    *sparser* rail's column move it backwards, so a place where the recorded offset drops
    is a spoke no path built from the denser rail's vocabulary can stand on.  The total
    drop is therefore the number of those steps this band's own connectivity asks for --
    two on the band this was written for, where the source runs one spoke from each of two
    adjacent inner columns into the same outer one.

    Read this as a demand, not an order: :func:`_band_vocabulary` hands it to
    :func:`_allowed_transitions` as a budget, and a band whose pattern never leans back
    keeps exactly the kinds it has always had.
    """
    if not nodes or inner_steps <= 0 or outer_steps <= 0:
        return 0
    offset = 0
    pinches = 0
    for inner_index, outer_index in sorted(nodes, key=lambda node: (node[1], node[0])):
        if not 0 <= inner_index <= inner_steps or not 0 <= outer_index <= outer_steps:
            continue
        place = outer_index - inner_index
        if place < offset:
            pinches += offset - place
        offset = place
    final_offset = outer_steps - inner_steps
    if final_offset < offset:
        pinches += offset - final_offset
    return min(pinches, inner_steps, outer_steps)


def _wide_face_budget(region, inner_steps, outer_steps):
    """How many faces in this band may cover two columns of its denser rail.

    A source band holding fewer faces than the denser of its two rails has columns that
    were never joined to the far side -- the model's own faces stand two columns wide
    there.  Until the search had a kind for that it had to spend a spoke on every column
    to reach the rail's end, and the surplus landed wherever the cost happened to leave
    it, which on a band whose far rail is an untouched part of the model is most of them.
    The budget says how many such faces the band itself reported, and nothing here reads
    coordinates, so a band that never needed one keeps exactly the two kinds it had.

    The count is anchored to the face records -- the row the ladder actually rebuilds --
    not to the region's whole face set: a region deeper than one row holds faces with no
    inner-rail corner that no ladder will ever draw, and counting them shrinks the budget
    by exactly their number, so the rebuilt band comes out that many faces heavier than
    the row it replaces.

    Rails of equal length are left alone however the source reads: a surplus on one rail
    has to be paid back on the other then, which is a different question than the one a
    wide face answers.
    """
    if inner_steps == outer_steps:
        return 0
    dense_steps = max(inner_steps, outer_steps)
    records = ((region or {}).get("source_faces") or {}).get("records") or ()
    faces = len(records) if records else len((region or {}).get("faces") or ())
    if not faces or faces >= dense_steps:
        return 0
    return min(
        dense_steps - faces,
        dense_steps // 2,
        min(inner_steps, outer_steps),
    )


def _allowed_transitions(
    inner_steps,
    outer_steps,
    wide_budget=0,
    pinch_budget=0,
):
    """The kinds one band's ladder may spend, in the order the search tries them.

    The dense rail's surplus is what decides the ordinary kinds, so a band whose inner rail
    is the short loop is never offered a face that spends the outer rail's column -- except
    when its own source band drew one, which is what ``pinch_budget`` says
    (:func:`_pairing_pinches`).  Without that exception the connectivity a fan and a pinch
    describe is simply not a path in the graph being searched, and no price can reach it.

    Both extra kinds go last, the wide one before the pinching one, so a band that does not
    need them answers with the kinds it has always had at an equal cost.
    """
    if inner_steps == outer_steps:
        return ("QUAD",)
    if inner_steps < outer_steps:
        surplus, wide, pinch = "OUTER_TRI", "OUTER_WIDE", "INNER_TRI"
    else:
        surplus, wide, pinch = "INNER_TRI", "INNER_WIDE", "OUTER_TRI"
    allowed = ["QUAD", surplus]
    if wide_budget > 0:
        allowed.append(wide)
    if pinch_budget > 0:
        allowed.append(pinch)
    return tuple(allowed)


def _band_vocabulary(region, inner_steps, outer_steps):
    """What this band's rails and its own source pairing permit, as one unit.

    Returns ``(allowed, wide_budget, pinch_budget)``.  Both call sites -- the solve and
    the seam's waypoint pruning -- have to agree, because a waypoint reachable under one
    reading of the vocabulary and unreachable under the other would drop a crossing the
    strip can actually route through.
    """
    budget = _wide_face_budget(region, inner_steps, outer_steps)
    pinches = _pairing_pinches(
        tuple((region or {}).get(_PAIRING_NODES) or ()),
        inner_steps,
        outer_steps,
    ) if budget else 0
    # A step that spends the sparser rail's column widens the strip by one face, and only a
    # wide face pays it back, so the band is never granted a pinch it has no wide face to
    # trade for.  That keeps the ceiling on the face count exactly where the source band put
    # it however many spokes the pairing stacks on one column.
    return (
        _allowed_transitions(inner_steps, outer_steps, budget, min(pinches, budget)),
        budget,
        min(pinches, budget),
    )


def _face_count_credit(kind, inner_steps, outer_steps):
    """What one step of this kind does to how many faces the band needs.

    A strip's face count is its denser rail's columns minus its wide faces plus its
    pinches: a face spanning two of the dense rail's columns saves one, and a spoke that
    spends the sparse rail's column costs one, because the length gap it should have closed
    now needs a wide face of its own.  Counting the two against each other, rather than
    counting wide faces alone, is what lets a band keep the source's face count while
    standing on the rungs the source drew.

    A band whose pairing asks for nothing has no kind here with a negative credit, so the
    count it spends is the wide count it always spent.
    """
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    shift = outer_step - inner_step
    if not shift:
        return 0
    if outer_steps > inner_steps:
        dense_step, sparse_step = outer_step, inner_step
    else:
        dense_step, sparse_step = inner_step, outer_step
    toward_dense = (shift > 0) == (outer_steps > inner_steps)
    if toward_dense:
        # A one-column surplus triangle keeps the count; every further dense column the
        # same face covers saves one.
        return dense_step - 1
    return -1 if dense_step == 0 and sparse_step else 0


def _seam_waypoint_nodes(waypoints, allowed, inner_steps, outer_steps):
    """The crossings' rung positions the search has to route through, in ladder order.

    A ladder starts at ``d = outer - inner == 0`` and ends at the difference between the
    two rail lengths, and the one triangle kind its rails permit moves ``d`` in a single
    direction, so a crossing outside that band -- or a set of them that cannot be visited
    in that one direction -- has no path at all.  The search would spend a whole sweep
    proving it and then drop every pin in the region, so the unreachable crossings are
    pruned here instead and fall back to the rung painter sliding them.  Of the rest the
    longest runnable run wins, earliest first, which leaves an already-reachable set
    untouched: only a step the search was going to lose can come back different.

    Returns ``(nodes, dropped)``, ``dropped`` carrying the rule that cut each position
    off so a slid rung stays traceable.
    """
    final_offset = outer_steps - inner_steps
    low = min(0, final_offset)
    high = max(0, final_offset)
    # An inner step is the only move that shrinks d, whether it spends one column of the
    # inner rail or two.  A QUAD-only strip is pinned to d == 0 by the band above, so
    # either direction reads the same there.  Where the pairing bought the strip a kind in
    # each direction, d can be walked back and forth at will, so no crossing is refused on
    # the order of the ones before it and the whole in-band set is kept.
    shifts = {_rail_shift(kind) for kind in allowed if _rail_shift(kind)}
    if len(shifts) > 1:
        direction = 0
    else:
        direction = -1 if any(shift < 0 for shift in shifts) else 1
    candidates = []
    dropped = []
    for inner_index, outer_index in sorted(set(waypoints)):
        if not 0 <= inner_index <= inner_steps or not 0 <= outer_index <= outer_steps:
            dropped.append((inner_index, outer_index, "lattice"))
            continue
        if not low <= outer_index - inner_index <= high:
            dropped.append((inner_index, outer_index, "band"))
            continue
        candidates.append((inner_index, outer_index))

    chains = []
    longest = ()
    for index, (inner_index, outer_index) in enumerate(candidates):
        offset = outer_index - inner_index
        chain = (index,)
        for previous_index in range(index):
            previous_inner, previous_outer = candidates[previous_index]
            if previous_outer > outer_index:
                continue
            if (offset - (previous_outer - previous_inner)) * direction < 0:
                continue
            extended = chains[previous_index] + (index,)
            if len(extended) > len(chain):
                chain = extended
        chains.append(chain)
        if len(chain) > len(longest):
            longest = chain
    nodes = tuple(candidates[index] for index in longest)
    dropped.extend(
        (inner_index, outer_index, "chain")
        for index, (inner_index, outer_index) in enumerate(candidates)
        if index not in longest
    )
    return nodes, tuple(sorted(dropped))


def _pairing_profile(nodes, inner_steps, outer_steps, is_closed):
    """How many of this band's own spokes were meant to leave each of its columns.

    A rebuilt rail answers its source with a *count*, not a position.  The source stacked
    four rungs on one inner column; a strip with fewer columns than the source drew can
    still spend four of its one-column steps there.  What it cannot do is stand on the outer
    columns the record names -- those belong to a rail with a different number of them, and
    the faces that would carry it from one to the next are the faces this band was never
    given: the count is fixed by the source, so a pattern that asks for nineteen faces at
    fifteen is not a price away from working, it is a different band.  A target only an
    untouched rail can hit prices nothing, so this counts spokes instead.

    The count is a thing the search *can* hit: once both rails and the face count are fixed,
    which steps are one-column steps is already settled arithmetic, and which column spends
    them is entirely the ladder's choice.

    It is returned cumulative rather than per column, because that is the form a step can be
    charged in -- "how many surplus steps should be burned before entering this column" --
    and it is the same information: a tally that matches at every entry matches column by
    column.  Where the source's columns survive the resample the two readings agree exactly,
    positions included; where they do not, this one still can.  The per column counts come
    back alongside because they are the reading of this record a person can check.

    The tally is stepped by ``count - 1`` and *not* by how many spokes sit above one, because
    the ladder's own arithmetic is signed: the number of surplus steps it has burned at any
    point is ``dense - sparse - wide``, which counts a column it jumps over as a step it
    *gained back*.  Clamping at zero would therefore hand a band with one empty column a
    total one bigger than any ladder at this face count can spend, and the shortfall would
    then be charged at every column after it -- the same uncatchable cliff that made the
    position target useless.  Signed, the tally sums to exactly what the pinned face count
    must spend, so a strip that stands all of these spokes where the source stood them scores
    zero and an empty column is a single column's miss rather than a debt to the end.
    """
    sparse_is_inner = inner_steps <= outer_steps
    sparse_steps = inner_steps if sparse_is_inner else outer_steps
    if not nodes or sparse_steps <= 0:
        return (), ()
    # A closed band's last column is its first, and the record names it either way.  An
    # open band's last column is a column of its own: folding it into the first would
    # charge a pinch that sits at the strip's end as surplus spent at its start.
    counts = [0] * (sparse_steps if is_closed else sparse_steps + 1)
    for inner_index, outer_index in nodes:
        place = inner_index if sparse_is_inner else outer_index
        if not 0 <= place <= sparse_steps:
            continue
        counts[place % sparse_steps if is_closed else place] += 1
    spent = 0
    profile = [0]
    for count in counts:
        spent += count - 1
        profile.append(spent)
    return tuple(profile), tuple(counts)


def _pairing_offset(
    boundary_geometry,
    kind,
    next_inner,
    next_outer,
    net_wide,
    inner_steps,
    outer_steps,
):
    """How many surplus steps this column burns over what the band's own pattern spent there.

    Read as the ladder walks off the column, because that is the last moment at which what
    stood on it can still be counted -- a step that stays on the rail's column has left the
    tally open.  And read off arithmetic the state already carries rather than off a counter
    of its own: a node on the dense rail's side of a ladder that has spent ``net_wide`` wide
    faces has burned ``dense - sparse - net_wide`` of its one-column steps, in whatever order
    it burned them, which is why pricing the profile costs one subtraction.
    """
    profile = boundary_geometry.pairing_profile
    if not profile:
        return 0.0
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    if outer_steps >= inner_steps:
        if inner_step != 1:
            return 0.0
        return float(next_outer - next_inner - net_wide - profile[next_inner])
    if outer_step != 1:
        return 0.0
    return float(next_inner - next_outer - net_wide - profile[next_outer])


def _doubled_place_cost(
    boundary_geometry,
    kind,
    next_inner,
    next_outer,
    inner_steps,
    outer_steps,
):
    """What it costs to land this step's doubled spoke on a column the source did not double.

    A step that stays on the sparser rail's column -- a surplus triangle or a wide face
    -- leaves two spokes on the column it arrived from, which is the pinch a fan pays
    for.  The cumulative profile can say how many of those a path should have spent by
    each column but never which column carries one, so a band whose source stacked its
    second spokes at its end could watch the search buy them all at its start for free.
    This charges the column itself against the source's own set.  The pinch kind that
    spends the *denser* rail's column is not here: it doubles a dense column, which the
    counts never tracked.
    """
    doubles = boundary_geometry.pairing_doubles
    if not doubles:
        return 0.0
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    if outer_steps > inner_steps:
        if inner_step:
            return 0.0
        column = next_inner
    else:
        if outer_step:
            return 0.0
        column = next_outer
    if column == len(doubles):
        # A closed band's last column is its first; an open band's last has a slot of
        # its own, and this index then simply names it.
        column = 0
    if doubles[column]:
        return 0.0
    return PINCH_PLACE_WEIGHT


def _surplus_names(allowed):
    """Which kinds this strip may spend a rail column with, for the seam-skip line.

    A band that was allowed a wide face has two surplus kinds to spend, so the single name
    this used to print is now a list.
    """
    return "+".join(kind for kind in allowed if kind != "QUAD") or "none"


def _waypoint_reach_diagnostic(nodes, dropped, allowed):
    """The pruned crossings with the rule that cut them off, for the seam-skip line.

    ``band`` says the strip can never reach that ``d = outer - inner`` whatever the other
    crossings ask for, ``chain`` that the position lost the monotone competition to the
    ones kept, and ``lattice`` that it is not a rung the ladder has at all.  A pruned
    crossing otherwise leaves only a slid rung behind, which names no reason.
    """
    dropped_text = " ".join(
        f"({inner_index}, {outer_index})={outer_index - inner_index}:{reason}"
        for inner_index, outer_index, reason in dropped
    )
    kept_text = " ".join(
        f"({inner_index}, {outer_index})={outer_index - inner_index}"
        for inner_index, outer_index in nodes
    )
    return (
        f"dropped=[{dropped_text}] kept=[{kept_text}] "
        f"triangle={_surplus_names(allowed)}"
    )


def _waypoint_diagnostic(nodes, allowed, boundary_geometry):
    """Per-node ``d`` plus the rung-crossing verdict, for the seam-skip line.

    :func:`._seam_waypoint_nodes` has already dropped every position no monotone ladder
    under ``allowed`` can reach, so a surviving turn-back in ``d = outer - inner`` would
    mean the two disagree; the expected reading is a flat ``d`` with one ``cross`` set,
    which names the node whose own rung the boundary test kills.  Read once per failed
    solve, never in the search loop, and it reuses positions the solve already cached.
    """
    offsets = ", ".join(str(outer - inner) for inner, outer in nodes)
    crossed = ", ".join(
        str(int(_rung_crosses_boundary(boundary_geometry, inner, outer)))
        for inner, outer in nodes
    )
    return (
        f"nodes={nodes} d=[{offsets}] cross=[{crossed}] "
        f"triangle={_surplus_names(allowed)}"
    )


def _on_seam_corridor(inner_index, outer_index, nodes):
    """Whether a node can still sit on a monotone path through every waypoint.

    A path only ever increases both indices, so a node has to be at or before one
    waypoint and at or after the next.  Intersecting each waypoint's own half-plane
    pair is exactly that, because the kept nodes are already monotone.
    """
    for waypoint_inner, waypoint_outer in nodes:
        if (
            inner_index > waypoint_inner or outer_index > waypoint_outer
        ) and (
            inner_index < waypoint_inner or outer_index < waypoint_outer
        ):
            return False
    return True


def _routes_around_waypoint(
    inner_index, outer_index, next_inner, next_outer, nodes
):
    """Whether a step changes sides of a waypoint without landing on it.

    The corridor alone is not enough: a quad from the column before a crossing to the
    row after it is a perfectly legal monotone step that leaves the rung with no node
    to paint on, which is the slide this is here to prevent.
    """
    for waypoint_inner, waypoint_outer in nodes:
        if (
            inner_index <= waypoint_inner
            and outer_index <= waypoint_outer
            and next_inner >= waypoint_inner
            and next_outer >= waypoint_outer
            and (inner_index, outer_index) != (waypoint_inner, waypoint_outer)
            and (next_inner, next_outer) != (waypoint_inner, waypoint_outer)
        ):
            return True
    return False


class _BoundaryGeometry:
    """Per-plan boundary data shared by the transition search."""

    __slots__ = (
        "inner_points",
        "outer_points",
        "epsilon_squared",
        "boundary_scale",
        "minimum",
        "cell_size",
        "buckets",
        "rung_cross_cache",
        "boundary_records",
        "pairing_profile",
        "pairing_doubles",
    )

    def __init__(
        self,
        inner_points,
        outer_points,
        epsilon_squared,
        boundary_scale,
        minimum,
        cell_size,
        buckets,
        boundary_records,
    ):
        self.inner_points = inner_points
        self.outer_points = outer_points
        self.epsilon_squared = epsilon_squared
        self.boundary_scale = boundary_scale
        self.minimum = minimum
        self.cell_size = cell_size
        self.buckets = buckets
        self.rung_cross_cache = {}
        self.boundary_records = boundary_records
        # The one thing here that is not measured from the rails: how many spokes this band's
        # own source rungs spent on each of its columns, filled in by the plan that owns the
        # search.  It rides along because the search and the local swap both price a step, and
        # the swap has to see the same money the search did.
        self.pairing_profile = ()
        # Which of the sparser rail's columns the source stacked a second spoke on, as one
        # boolean per column.  The cumulative profile above cannot say *where* a doubled
        # spoke belongs -- two paths with the same tally read identically through it --
        # so a step that doubles a column is also charged against this set directly.
        self.pairing_doubles = ()


def _boundary_bounds_from_points(points):
    points = tuple(points)
    minimum = points[0].copy()
    maximum = points[0].copy()
    for point in points[1:]:
        for axis in range(3):
            minimum[axis] = min(minimum[axis], point[axis])
            maximum[axis] = max(maximum[axis], point[axis])
    return minimum, maximum


def _prepare_boundary_geometry(inner, outer, is_closed):
    """Copy boundary geometry and build a spatial index for segment queries."""
    inner_points = tuple(_point(vertex) for vertex in inner)
    outer_points = tuple(_point(vertex) for vertex in outer)
    all_points = (*inner_points, *outer_points)
    minimum, maximum = _boundary_bounds_from_points(all_points)
    extent = maximum - minimum
    epsilon_squared = max(extent.length_squared * 1e-14, 1e-20)
    boundary_scale = max(extent.length, 1e-12)

    inner_segments = tuple(zip(inner_points, inner_points[1:]))
    outer_segments = tuple(zip(outer_points, outer_points[1:]))
    if is_closed:
        inner_segments += ((inner_points[-1], inner_points[0]),)
        outer_segments += ((outer_points[-1], outer_points[0]),)

    segment_count = max(len(inner_segments), len(outer_segments), 1)
    # A boundary is a curve inside a thin slab, so cells should grow with area and
    # not with volume.  At n**(1/3) a single cell swallowed about ten segments and a
    # query handed back ~33 candidates while only ~11 of them could touch the rung at
    # all, so the sweep cost more than the index saved.
    cells_per_axis = min(32, max(4, int(round(segment_count ** (2.0 / 3.0)))))
    cell_size = max(extent.length / cells_per_axis, epsilon_squared ** 0.5 * 4.0)
    buckets = [{}, {}]
    for boundary_index, segments in enumerate((inner_segments, outer_segments)):
        boundary_buckets = buckets[boundary_index]
        for segment_index, (first, second) in enumerate(segments):
            cell_ranges = []
            for axis in range(3):
                lower = min(first[axis], second[axis])
                upper = max(first[axis], second[axis])
                start = math.floor((lower - minimum[axis]) / cell_size)
                end = math.floor((upper - minimum[axis]) / cell_size)
                cell_ranges.append(range(start, end + 1))
            for x_index in cell_ranges[0]:
                for y_index in cell_ranges[1]:
                    for z_index in cell_ranges[2]:
                        boundary_buckets.setdefault(
                            (x_index, y_index, z_index),
                            set(),
                        ).add(segment_index)

    # Per segment: the axis-aligned box the pair test compares against, and the
    # direction plus squared length the crossing test recomputes otherwise.
    boundary_records = []
    for segments in (inner_segments, outer_segments):
        boxes = []
        directions = []
        for first, second in segments:
            boxes.append(
                (
                    min(first[0], second[0]),
                    max(first[0], second[0]),
                    min(first[1], second[1]),
                    max(first[1], second[1]),
                    min(first[2], second[2]),
                    max(first[2], second[2]),
                )
            )
            direction = second - first
            directions.append((direction, direction.length_squared))
        boundary_records.append((segments, tuple(boxes), tuple(directions)))

    return _BoundaryGeometry(
        inner_points,
        outer_points,
        epsilon_squared,
        boundary_scale,
        minimum,
        cell_size,
        tuple(buckets),
        tuple(boundary_records),
    )


def _rung_cell_ranges(boundary_geometry, first, second):
    """The cell intervals a rung bounding box covers on each axis."""
    epsilon = boundary_geometry.epsilon_squared ** 0.5
    minimum = boundary_geometry.minimum
    cell_size = boundary_geometry.cell_size
    cell_ranges = []
    for axis in range(3):
        first_axis = first[axis]
        second_axis = second[axis]
        start = math.floor(
            (min(first_axis, second_axis) - epsilon - minimum[axis]) / cell_size
        )
        end = math.floor(
            (max(first_axis, second_axis) + epsilon - minimum[axis]) / cell_size
        )
        cell_ranges.append(range(start, end + 1))
    return cell_ranges


def _indexed_segments(boundary_geometry, boundary_index, cell_ranges):
    """Return indices of boundary segments whose cells overlap a rung box."""
    indices = set()
    buckets = boundary_geometry.buckets[boundary_index]
    for x_index in cell_ranges[0]:
        for y_index in cell_ranges[1]:
            for z_index in cell_ranges[2]:
                indices.update(buckets.get((x_index, y_index, z_index), ()))
    return indices


def _rung_crosses_boundary(boundary_geometry, inner_index, outer_index):
    """Reject a candidate rung that cuts through either ordered boundary.

    The answer depends only on the wrapped index pair and on the frozen geometry,
    and the DP proposes every position once per parent state, so one position is
    tested at most once per plan.
    """
    inner_points = boundary_geometry.inner_points
    outer_points = boundary_geometry.outer_points
    position = (inner_index % len(inner_points), outer_index % len(outer_points))
    cached = boundary_geometry.rung_cross_cache.get(position)
    if cached is not None:
        return cached
    crossed, examined, probes = _position_crosses_boundary(
        boundary_geometry,
        position,
    )
    accumulate_scan("plan-boundary-candidates", 0.0, examined)
    accumulate_scan("plan-boundary-cell-probes", 0.0, probes)
    boundary_geometry.rung_cross_cache[position] = crossed
    return crossed


def _position_crosses_boundary(boundary_geometry, position):
    """Return (crossed, candidates examined, cells probed) for one index pair.

    The hoisted pieces below are the same float operations the pair test
    performs; they are moved out of the candidate loop because a position fixes
    one segment and sweeps dozens of the others.  ``probes`` counts the bucket
    lookups the finer grid buys, since a long rung can cover many empty cells.
    """
    epsilon_squared = boundary_geometry.epsilon_squared
    first = boundary_geometry.inner_points[position[0]]
    second = boundary_geometry.outer_points[position[1]]
    epsilon = epsilon_squared ** 0.5
    first_x = first[0]
    first_y = first[1]
    first_z = first[2]
    second_x = second[0]
    second_y = second[1]
    second_z = second[2]
    rung_direction = second - first
    rung_length_squared = rung_direction.length_squared
    query_max_x = (first_x if first_x > second_x else second_x) + epsilon
    query_min_x = first_x if first_x < second_x else second_x
    query_max_y = (first_y if first_y > second_y else second_y) + epsilon
    query_min_y = first_y if first_y < second_y else second_y
    query_max_z = (first_z if first_z > second_z else second_z) + epsilon
    query_min_z = first_z if first_z < second_z else second_z
    examined = 0
    probes = 0
    cell_ranges = _rung_cell_ranges(boundary_geometry, first, second)
    cell_footprint = len(cell_ranges[0]) * len(cell_ranges[1]) * len(cell_ranges[2])
    for boundary_index, (segments, boxes, directions) in enumerate(
        boundary_geometry.boundary_records
    ):
        probes += cell_footprint
        for index in _indexed_segments(
            boundary_geometry,
            boundary_index,
            cell_ranges,
        ):
            examined += 1
            lower_x, upper_x, lower_y, upper_y, lower_z, upper_z = boxes[index]
            # _boxes_overlap's own rejection, run first so a distant segment costs
            # no Vector subtraction at all: when the boxes miss, the candidate can
            # never be reported as crossing.
            if (
                query_max_x < lower_x
                or upper_x + epsilon < query_min_x
                or query_max_y < lower_y
                or upper_y + epsilon < query_min_y
                or query_max_z < lower_z
                or upper_z + epsilon < query_min_z
            ):
                continue
            start, end = segments[index]
            start_x = start[0]
            end_x = end[0]
            # A rung is expected to meet its own boundary at its endpoint.  A
            # squared length is never smaller than its own squared x term, so
            # these four x-component tests prove the original test false; where
            # they pass, the original expression still decides.
            if (
                abs(first_x - start_x) > epsilon
                and abs(second_x - start_x) > epsilon
                and abs(first_x - end_x) > epsilon
                and abs(second_x - end_x) > epsilon
            ):
                touches_endpoint = False
            else:
                touches_endpoint = any(
                    (first - boundary_point).length_squared <= epsilon_squared
                    or (second - boundary_point).length_squared <= epsilon_squared
                    for boundary_point in (start, end)
                )
            if touches_endpoint:
                continue
            segment_direction, segment_length_squared = directions[index]
            if _crossing_after_box_overlap(
                first,
                second,
                start,
                end,
                rung_direction,
                segment_direction,
                rung_length_squared,
                segment_length_squared,
                epsilon_squared,
            ):
                return True, examined, probes
    return False, examined, probes


def _consecutive_rungs_cross(
    boundary_geometry,
    first_inner,
    first_outer,
    second_inner,
    second_outer,
):
    """Reject a step whose rung cuts through the previous rung.

    Index-monotone transitions can still cross in space when the two rails are
    misaligned.  A crossed rung leaves a bowtie in the mesh, and the next run
    can no longer read a clean outer boundary from it.
    """
    if first_inner == second_inner or first_outer == second_outer:
        return False
    inner_points = boundary_geometry.inner_points
    outer_points = boundary_geometry.outer_points
    return _segments_intersect(
        inner_points[first_inner % len(inner_points)],
        outer_points[first_outer % len(outer_points)],
        inner_points[second_inner % len(inner_points)],
        outer_points[second_outer % len(outer_points)],
        boundary_geometry.epsilon_squared,
    )


def _skipped_column_cost(boundary_geometry, kind, next_inner, next_outer):
    """What the rung inside a two-column face would have cost had it been drawn.

    Such a face leaves one column of the denser rail without a spoke, which is what the
    source band did with it.  Charging nothing there would let the search buy the skip
    wherever the missing rung is worst, so the rung is still measured -- it is simply
    never written into the mesh.
    """
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    skipped_inner = next_inner - max(0, inner_step - 1)
    skipped_outer = next_outer - max(0, outer_step - 1)
    if skipped_inner == next_inner and skipped_outer == next_outer:
        return 0.0
    inner_points = boundary_geometry.inner_points
    outer_points = boundary_geometry.outer_points
    rung = (
        inner_points[skipped_inner % len(inner_points)]
        - outer_points[skipped_outer % len(outer_points)]
    ).length
    normalized_rung = rung / boundary_geometry.boundary_scale
    return RUNG_LENGTH_WEIGHT * normalized_rung * normalized_rung


def _step_base_cost(
    face,
    kind,
    inner,
    outer,
    next_inner,
    next_outer,
    inner_boundary,
    outer_boundary,
    inner_steps,
    outer_steps,
    boundary_geometry,
    reflex_reject=True,
):
    """What one step costs before the pairing pattern is consulted.

    Everything in here reads only the step's own geometry, so the search caches it per
    ``(inner, outer, kind)`` and adds the pairing term -- the one part that depends on
    how many wide faces the path has already spent -- on top of the cached value.

    A step spanning two columns of one rail is read once more before it is priced:
    :func:`wide_face_reflex_metrics` says whether the span re-enters -- an interior
    angle past 180 degrees, which the strict sweep refuses outright -- and how
    extreme its worst corner runs, which every sweep charges, because the edge-ratio
    shape terms cannot tell a long diagonal kite from the band's plain elongated
    quads and the kite is the face nobody wants to look at.
    """
    quality = face_quality_cost(face, None)
    if quality is None:
        return None
    advance = TRANSITION_ADVANCE[kind]
    reflex_cost = 0.0
    if advance[0] > 1 or advance[1] > 1:
        reflex, extremity = wide_face_reflex_metrics(face)
        if reflex > REFLEX_SIN_EPSILON:
            if reflex_reject:
                return None
            reflex_cost = REFLEX_PENALTY_WEIGHT
        reflex_cost += WIDE_ANGLE_WEIGHT * extremity * extremity
    rung = (
        boundary_geometry.inner_points[next_inner % len(inner)]
        - boundary_geometry.outer_points[next_outer % len(outer)]
    ).length
    normalized_rung = rung / boundary_geometry.boundary_scale
    progress_error = abs(
        inner_boundary.parameters[next_inner % len(inner_boundary.parameters)]
        - outer_boundary.parameters[next_outer % len(outer_boundary.parameters)]
    )
    normalized_error = abs(
        next_inner / max(inner_steps, 1) - next_outer / max(outer_steps, 1)
    )
    shape_weight = 1.35 if len(face) == 3 else 0.75
    return (
        shape_weight * min(quality, 50.0)
        + RUNG_LENGTH_WEIGHT * normalized_rung * normalized_rung
        + 0.08 * progress_error
        + 0.8 * normalized_error
        + reflex_cost
        + _doubled_place_cost(
            boundary_geometry,
            kind,
            next_inner,
            next_outer,
            inner_steps,
            outer_steps,
        )
        + _skipped_column_cost(
            boundary_geometry, kind, next_inner, next_outer
        )
    )


def _step_cost(
    face,
    kind,
    inner,
    outer,
    next_inner,
    next_outer,
    net_wide,
    inner_boundary,
    outer_boundary,
    inner_steps,
    outer_steps,
    boundary_geometry,
    reflex_reject=True,
):
    base_cost = _step_base_cost(
        face,
        kind,
        inner,
        outer,
        next_inner,
        next_outer,
        inner_boundary,
        outer_boundary,
        inner_steps,
        outer_steps,
        boundary_geometry,
        reflex_reject,
    )
    if base_cost is None:
        return None
    pairing_offset = _pairing_offset(
        boundary_geometry,
        kind,
        next_inner,
        next_outer,
        net_wide,
        inner_steps,
        outer_steps,
    )
    return base_cost + PAIRING_TARGET_WEIGHT * pairing_offset * pairing_offset


def _transition_pair_balance_penalty(transitions, start, end):
    """Give a small local penalty to repeated same-side surplus steps."""
    left = max(0, start - 1)
    right = min(len(transitions), end + 1)
    penalty = 0.0
    for first, second in zip(transitions[left:right], transitions[left + 1:right]):
        if first == second and _rail_shift(first):
            penalty += 0.18
    return penalty


def _local_transition_pair_score(
    transitions,
    start_index,
    start_inner,
    start_outer,
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    inner_steps,
    outer_steps,
    is_closed,
    boundary_geometry,
    triangle_count=0,
    vector_cache=None,
    reflex_reject=True,
):
    """Score two adjacent transitions without rebuilding the whole strip."""
    inner_index = start_inner
    outer_index = start_outer
    # The wide tally the search would have been carrying at this point, recovered by adding
    # up what the steps before it each cost.  A swap only ever trades two steps at
    # ``start_index``, so the run in front of it is the same run in either order.
    net_wide = sum(
        _face_count_credit(kind, inner_steps, outer_steps)
        for kind in transitions[:start_index]
    )
    score = 0.0
    previous_kind = transitions[start_index - 1] if start_index else None
    for kind in transitions[start_index : start_index + 2]:
        next_inner, next_outer = _advance(kind, inner_index, outer_index)
        if next_inner > inner_steps or next_outer > outer_steps:
            return None
        if not (
            is_closed
            and next_inner == inner_steps
            and next_outer == outer_steps
        ) and _rung_crosses_boundary(boundary_geometry, next_inner, next_outer):
            return None
        if _consecutive_rungs_cross(
            boundary_geometry,
            inner_index,
            outer_index,
            next_inner,
            next_outer,
        ):
            return None
        face = _transition_face(inner, outer, inner_index, outer_index, kind)
        net_wide += _face_count_credit(kind, inner_steps, outer_steps)
        step_cost = _step_cost(
            face,
            kind,
            inner,
            outer,
            next_inner,
            next_outer,
            net_wide,
            inner_boundary,
            outer_boundary,
            inner_steps,
            outer_steps,
            boundary_geometry,
            reflex_reject,
        )
        if step_cost is None:
            return None
        score += step_cost
        score += _triangle_distribution_cost(
            kind,
            inner_index,
            outer_index,
            next_inner,
            next_outer,
            inner_steps,
            outer_steps,
            triangle_count,
        )
        score += _rung_continuity_cost(
            boundary_geometry,
            previous_kind,
            inner_index,
            outer_index,
            next_inner,
            next_outer,
            vector_cache,
        )
        previous_kind = kind
        inner_index, outer_index = next_inner, next_outer
    return score


def _beautify_transitions(
    transitions,
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    is_closed,
    boundary_geometry,
    waypoints=(),
    reflex_reject=True,
):
    """Make a few safe local swaps after the strip's path is selected.

    Swapping two adjacent transitions moves where a strip's surplus triangles sit, so
    it is run over the whole strip: a triangle can end up on either side of whichever
    column the seam took.  A swap is refused where it would move a seam's own node,
    because the rung painter then slides back off the pinned vertex.
    """
    transitions = list(transitions)
    inner_steps = len(inner) if is_closed else len(inner) - 1
    outer_steps = len(outer) if is_closed else len(outer) - 1
    triangle_count = abs(inner_steps - outer_steps)
    vector_cache = {}

    for _pass in range(2):
        changed = False
        inner_index = 0
        outer_index = 0
        for index in range(len(transitions) - 1):
            first, second = transitions[index : index + 2]
            if first == second:
                inner_index, outer_index = _advance(
                    first,
                    inner_index,
                    outer_index,
                )
                continue
            if waypoints and (
                _advance(first, inner_index, outer_index) in waypoints
                or _advance(second, inner_index, outer_index) in waypoints
            ):
                inner_index, outer_index = _advance(
                    first,
                    inner_index,
                    outer_index,
                )
                continue

            current_score = _local_transition_pair_score(
                transitions,
                index,
                inner_index,
                outer_index,
                inner,
                outer,
                inner_boundary,
                outer_boundary,
                inner_steps,
                outer_steps,
                is_closed,
                boundary_geometry,
                triangle_count,
                vector_cache,
                reflex_reject,
            )
            if current_score is None:
                inner_index, outer_index = _advance(
                    first,
                    inner_index,
                    outer_index,
                )
                continue

            current_balance = _transition_pair_balance_penalty(
                transitions,
                index,
                index + 2,
            )
            transitions[index : index + 2] = (second, first)
            alternate_score = _local_transition_pair_score(
                transitions,
                index,
                inner_index,
                outer_index,
                inner,
                outer,
                inner_boundary,
                outer_boundary,
                inner_steps,
                outer_steps,
                is_closed,
                boundary_geometry,
                triangle_count,
                vector_cache,
                reflex_reject,
            )
            alternate_balance = _transition_pair_balance_penalty(
                transitions,
                index,
                index + 2,
            )
            transitions[index : index + 2] = (first, second)

            if (
                alternate_score is not None
                and alternate_score + alternate_balance
                < current_score + current_balance - 1e-9
            ):
                transitions[index : index + 2] = (second, first)
                changed = True
            inner_index, outer_index = _advance(
                transitions[index],
                inner_index,
                outer_index,
            )
        if not changed:
            break
    return tuple(transitions)


def _sweep_ladder(
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    is_closed,
    boundary_geometry,
    waypoints,
    allowed,
    budget,
    inner_steps,
    outer_steps,
    wide_pruning,
    reflex_reject=True,
):
    """One full sweep of the ladder's dynamic program: the states at the far corner.

    A quad moves inner+outer by two and a triangle by one, so diagonal d is fed by
    round d-2 (quads and wide faces, which both spend two columns) then round d-1
    (triangles) and a round must read every part in that order.  One flat dict plus a
    diagonal filter made every round re-scan all history -- ~800k dead iterations to
    reach ~24k live ones.  The fourth part of a state key counts the wide faces spent,
    less any pinch that has to be paid back with one, because a wide face is cheaper
    than the two it replaces and a search left to price its own face count would take
    every chance it was given.  The budget is what the source band reported, so the
    count is what pins the rebuilt band to the same number of faces.  Where there is no
    pinch to fund the count never leaves the wide count it has always been, which
    leaves the states -- and the answer -- exactly as they were.

    Returns ``(states, parents, expanded)``: the far corner's states as
    ``key -> cost``, one ``key -> (parent key, kind)`` link per state ever written,
    and the number of states expanded.  A state carries no transition list of its
    own -- copying the whole run onto every candidate cost more than the geometry it
    was priced with -- so the winner's run is replayed off the parent links instead.
    Every step advances at least one column, so a layer is final by the time it is
    expanded and a link can never be rewritten from under a child that already read
    it.

    ``wide_pruning`` drops every state whose remaining dense-rail columns can no longer
    fund the wide faces the budget still asks for -- two columns apiece -- because such
    a state is dead however cheap it was to reach.  The planner no longer enables it:
    the soft face-count bid (:data:`FACE_COUNT_SOFT_WEIGHT`) prices finals short of the
    budget instead of discarding them, which is exactly the set pruning would have
    thrown away.  The parameter stays for the out-of-Blender sweep tests, which assert
    a pruned and an unpruned run still land on the same state.
    """
    triangle_count = abs(inner_steps - outer_steps)
    # What is left of the rectangle once the round structure is fixed.  Only the steps
    # that shift d one way close this strip's length gap, so d moves one way only and
    # every prefix of a completable path has to stay between the start and the goal
    # offsets.  A state outside that band is not merely lost on its own account: its
    # parents are outside too, so no surviving state is reached through it and dropping
    # it cannot reorder, reprice or retie anything.  The band is therefore tied to the
    # one-direction rule rather than assumed, and gives up by itself if a kind ever
    # shifts d the other way -- a wider search, not a wrong one.
    final_offset = outer_steps - inner_steps
    low_offset = min(0, final_offset)
    high_offset = max(0, final_offset)
    band_limited = (
        len({_rail_shift(kind) > 0 for kind in allowed if _rail_shift(kind)}) <= 1
    )
    layers = {0: {(0, 0, None, 0): 0.0}}
    parents = {}
    # One geometric price per (column pair, kind): the boundary checks, the face's own
    # quality and the column bookkeeping below read nothing about how the path arrived
    # here, so every predecessor and wide-count variant of the same step reuses them.
    # Only the pairing pattern and the rung continuity stay priced per variant, because
    # those two do read the path.  False marks a step no path may take at all.
    step_cache = {}
    # One rung vector per node, shared by the three reads one continuity price makes.
    vector_cache = {}
    expanded = 0
    for total in range(inner_steps + outer_steps):
        tri_layer = {}
        quad_layer = {}
        wide_layer = {}
        for (inner_index, outer_index, previous_kind, wide_used), state in layers.pop(
            total
        ).items():
            if wide_pruning:
                if outer_steps >= inner_steps:
                    remaining_dense = outer_steps - outer_index
                else:
                    remaining_dense = inner_steps - inner_index
                if wide_used + remaining_dense // 2 < budget:
                    continue
            expanded += 1
            prior_cost = state
            for kind in allowed:
                advance = TRANSITION_ADVANCE[kind]
                next_inner = inner_index + advance[0]
                next_outer = outer_index + advance[1]
                if next_inner > inner_steps or next_outer > outer_steps:
                    continue
                width = advance[0] + advance[1]
                next_wide = wide_used + _face_count_credit(
                    kind,
                    inner_steps,
                    outer_steps,
                )
                if next_wide > budget:
                    continue
                if band_limited and not (
                    low_offset <= next_outer - next_inner <= high_offset
                ):
                    continue
                if waypoints and (
                    not _on_seam_corridor(next_inner, next_outer, waypoints)
                    or _routes_around_waypoint(
                        inner_index,
                        outer_index,
                        next_inner,
                        next_outer,
                        waypoints,
                    )
                ):
                    continue
                cache_key = (inner_index, outer_index, kind)
                cached = step_cache.get(cache_key)
                if cached is None:
                    if (
                        is_closed
                        and next_inner == inner_steps
                        and next_outer == outer_steps
                    ):
                        crosses_boundary = False
                    else:
                        crosses_boundary = _rung_crosses_boundary(
                            boundary_geometry,
                            next_inner,
                            next_outer,
                        )
                    if not crosses_boundary:
                        crosses_boundary = _consecutive_rungs_cross(
                            boundary_geometry,
                            inner_index,
                            outer_index,
                            next_inner,
                            next_outer,
                        )
                    if crosses_boundary:
                        cached = False
                    else:
                        face = _transition_face(
                            inner,
                            outer,
                            inner_index,
                            outer_index,
                            kind,
                        )
                        base_cost = _step_base_cost(
                            face,
                            kind,
                            inner,
                            outer,
                            next_inner,
                            next_outer,
                            inner_boundary,
                            outer_boundary,
                            inner_steps,
                            outer_steps,
                            boundary_geometry,
                            reflex_reject,
                        )
                        if base_cost is None:
                            cached = False
                        else:
                            cached = base_cost + _triangle_distribution_cost(
                                kind,
                                inner_index,
                                outer_index,
                                next_inner,
                                next_outer,
                                inner_steps,
                                outer_steps,
                                triangle_count,
                            )
                    step_cache[cache_key] = cached
                if cached is False:
                    continue
                pairing_offset = _pairing_offset(
                    boundary_geometry,
                    kind,
                    next_inner,
                    next_outer,
                    next_wide,
                    inner_steps,
                    outer_steps,
                )
                continuity_cost = _rung_continuity_cost(
                    boundary_geometry,
                    previous_kind,
                    inner_index,
                    outer_index,
                    next_inner,
                    next_outer,
                    vector_cache,
                )
                candidate_cost = (
                    prior_cost
                    + cached
                    + PAIRING_TARGET_WEIGHT * pairing_offset * pairing_offset
                    + continuity_cost
                )
                key = (next_inner, next_outer, kind, next_wide)
                if width == 2:
                    layer = quad_layer
                elif width == 1:
                    layer = tri_layer
                else:
                    layer = wide_layer
                previous = layer.get(key)
                if previous is None or candidate_cost < previous:
                    layer[key] = candidate_cost
                    parents[key] = (
                        (inner_index, outer_index, previous_kind, wide_used),
                        kind,
                    )
        # Each step lands in the round its own width reaches.  None of the three may
        # assign: round total-1's wide face has already arrived in total+2, and the
        # quad that lands there one round later has to join it rather than replace it.
        # A key names its kind, so two rounds can never offer the same state and an
        # update has nothing to overwrite.
        for offset, layer in ((1, tri_layer), (2, quad_layer), (3, wide_layer)):
            ahead = layers.get(total + offset)
            if ahead is None:
                layers[total + offset] = layer
            else:
                ahead.update(layer)
    return layers[inner_steps + outer_steps], parents, expanded


def _replay_transitions(key, parents):
    """The run of kinds that produced one state, walked back off the parent links."""
    kinds = []
    link = parents.get(key)
    while link is not None:
        key, kind = link
        kinds.append(kind)
        link = parents.get(key)
    kinds.reverse()
    return tuple(kinds)


def _build_transitions(
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    is_closed,
    boundary_geometry,
    waypoints=(),
    region=None,
    reflex_reject=True,
):
    """Solve the whole ladder: cheapest monotone path between two ordered rails.

    Every rail column is attained by any monotone path that spends no wide step, so on a
    band that needs none whichever vertex a crossing punctured is already guaranteed to
    carry a rung once this returns -- see :func:`.seams.region_seam_rungs`.  That
    guarantee is not enough either way: the rung it finds can sit a column off the vertex
    the sampler pinned, and the face in between then straddles two UV islands.
    ``waypoints`` are the nodes :func:`.seams` says a seam crossing needs, and the search
    may not route around them -- which is also what stops a wide face from ever hiding
    the one column a crossing landed on.

    ``reflex_reject`` refuses every two-column face that re-enters -- an interior angle
    past 180 degrees.  A band whose budget pins wide faces onto a rail that bends
    toward the sparse rail everywhere it can span them then has no path at all, so the
    caller (:func:`_search_ladder`) repeats this once with the refusal dropped: the
    re-entrant face is priced at :data:`REFLEX_PENALTY_WEIGHT` instead, bought only
    when every clean placement is gone.
    """
    inner_steps = len(inner) if is_closed else len(inner) - 1
    outer_steps = len(outer) if is_closed else len(outer) - 1
    allowed, budget, _pinch_budget = _band_vocabulary(
        region,
        inner_steps,
        outer_steps,
    )
    for level_reject in ((reflex_reject, False) if reflex_reject else (False,)):
        states, parents, expanded = _sweep_ladder(
            inner,
            outer,
            inner_boundary,
            outer_boundary,
            is_closed,
            boundary_geometry,
            waypoints,
            allowed,
            budget,
            inner_steps,
            outer_steps,
            False,
            level_reject,
        )
        accumulate_scan("plan-expand", 0.0, expanded)
        if states:
            break
    else:
        raise ValueError(pgettext("No valid ordered strip path was found."))
    # The band's face count is a bid, not a decree: the source reported how many of
    # its dense rail's columns go unjoined, and a ladder honouring exactly that count
    # buys a wide face for each -- but a wide face is only worth buying where it sits
    # clean.  Every final, whatever wide count it reached, is therefore priced with
    # FACE_COUNT_SOFT_WEIGHT per face it would add over the source band's count, so a
    # band whose budget only buys ugly kites drifts up to the face count its geometry
    # actually wants (the ladder line then prints wide=got/budget short), while a band
    # whose wides sit clean keeps the source's count for free.  The prefix cap above
    # still forbids *exceeding* the budget -- fewer faces than the source drew is the
    # direction kites come from, and that trade is never for sale.
    candidates = [
        (
            states[key] + FACE_COUNT_SOFT_WEIGHT * max(0, budget - key[3]),
            _replay_transitions(key, parents),
        )
        for key in states
    ]
    best = min(candidates, key=lambda state: state[0])
    wide_final = sum(
        _face_count_credit(kind, inner_steps, outer_steps)
        for kind in best[1]
    )
    if DIAGNOSE_LADDER and region is not None:
        print_ladder_dp(
            region,
            inner_steps,
            outer_steps,
            allowed,
            sorted(candidates, key=lambda state: state[0])[:2],
            waypoints,
            boundary_geometry.pairing_profile,
            (wide_final, budget) if budget else (),
        )
    return best


def ladder_steps(region, inner_vertices, outer_vertices):
    """The size of the grid a region's ladder walks.

    A saved transition sequence is a run of advances across exactly this grid, so the
    pair is both what the search is solved against and what a replay has to match.
    """
    if region["closed"]:
        return len(inner_vertices), len(outer_vertices)
    return len(inner_vertices) - 1, len(outer_vertices) - 1


def frozen_ladder(ladders, region, inner_vertices, outer_vertices, refresh=False):
    """The wiring this step may replay, or None when the search has to run again.

    Only a step that leaves the ladder's grid the same size has anything to say about a
    saved sequence, which is precisely what the shape axes are: :mod:`.curves` keeps a
    path's sample count alone unless the count wheel moved, so the rails advance over
    the same number of columns and the saved run of transitions still names faces.

    ``refresh`` is the step taken with no shape applied -- the session's baseline, run
    first and again on right-click cancel.  It re-solves even when the grid matches,
    because a cancel that replayed a wiring the user had since flipped would no longer
    land on the mesh the session started from.
    """
    if ladders is None or refresh:
        return None
    entry = ladders.get(region["region_index"])
    if entry is None:
        return None
    if entry["steps"] != ladder_steps(region, inner_vertices, outer_vertices):
        return None
    return entry


def outer_boundary_order(inner_vertices, outer_vertices, region, decision=None):
    """The direction a region's outer rail is walked in, and the choice that made it.

    Both rails have to be read in the same direction for a rung to join sensible
    pairs, so the choice is made once here and every later step -- the seam's rung
    lookup, the corner transfer, the ladder solve -- uses the same order.

    A ``decision`` from :func:`align_outer_boundary` is replayed instead of a new one
    being made, and comes back out again so the caller can freeze the two rails'
    pairing as one unit with the ladder solved on it.

    The replayed order is also what the source band's own rungs are counted in, so both
    branches record that reading for :func:`build_ordered_strip_plan` to solve against:
    a frozen ladder never saw the nodes, and the one solved on the next tick has to be
    pinned by the same numbering the rail is actually walked in.
    """
    if region.get("phase_locked"):
        region[_PAIRING_NODES] = ()
        return list(outer_vertices), None
    if decision is None:
        started = time.perf_counter()
        aligned, chosen = align_outer_boundary(
            inner_vertices,
            outer_vertices,
            region["closed"],
            region=region,
        )
        accumulate_scan("plan-align", time.perf_counter() - started, 1)
    else:
        if DIAGNOSE_LADDER:
            print_outer_replay(region, decision)
        aligned = apply_outer_decision(outer_vertices, decision, region["closed"])
        chosen = decision
    region[_PAIRING_NODES] = _source_pairing_nodes(
        region, inner_vertices, outer_vertices, chosen, region["closed"]
    )
    return aligned, chosen


def _ladder_plan(inner_boundary, outer_boundary, transitions, score, closed):
    """Turn one transition sequence into the faces and nodes it walks out."""
    started = time.perf_counter()
    inner_index = 0
    outer_index = 0
    faces = []
    nodes = [(0, 0)]
    for kind in transitions:
        faces.append(
            _transition_face(
                inner_boundary.vertices,
                outer_boundary.vertices,
                inner_index,
                outer_index,
                kind,
            )
        )
        inner_index, outer_index = _advance(kind, inner_index, outer_index)
        nodes.append((inner_index, outer_index))

    if closed:
        nodes.pop()
    plan = StripPlan(
        tuple(inner_boundary.vertices),
        tuple(outer_boundary.vertices),
        tuple(transitions),
        tuple(faces),
        score,
        inner_boundary.parameters,
        outer_boundary.parameters,
        tuple(nodes),
    )
    accumulate_scan("plan-faces", time.perf_counter() - started, len(transitions))
    return plan


def _finish_ladder_plan(plan, inner, outer, region):
    """Reject a ladder that cannot stand on the rails it was solved for.

    A replayed sequence arrives here too, which is what makes freezing a wiring safe:
    every check is geometric, so a shape tick that pushed a frozen rung across the
    boundary or into a degenerate face loses the replay rather than shipping the face.
    """
    started = time.perf_counter()
    validate_ordered_strip_plan(plan, inner, outer, region)
    if diagnose_ordered_strip_geometry(plan, inner, outer, region):
        raise ValueError(pgettext("The ordered strip contains intersecting edges."))
    accumulate_scan("plan-validate", time.perf_counter() - started, len(plan.faces))


def _search_ladder(
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    closed,
    boundary_geometry,
    allowed,
    seam_nodes,
    region,
):
    """Solve the ladder: the search, then the local swap over what it chose.

    Returns ``(transitions, score, complete, swapped)``.  ``complete`` is False for the
    answers the strip is allowed to give in a degraded form: routing around every seam
    waypoint refused, so the crossings fall back to positional matching -- or every
    clean placement of the band's wide faces refused, so one re-entrant face was priced
    in instead of losing the step.  A degraded ladder is never frozen, because the seam's
    rung would then stay off the vertex the sampler pinned for as long as the shape axes
    were scrolled.  ``swapped`` only says whether the local swap rewrote what the search
    chose, which is a diagnostic question, not one the rebuild asks itself.
    """
    started = time.perf_counter()
    attempts = 1
    complete = True
    reflex_reject = True
    try:
        score, transitions = _build_transitions(
            inner,
            outer,
            inner_boundary,
            outer_boundary,
            closed,
            boundary_geometry,
            seam_nodes,
            region=region,
        )
    except ValueError as strict_error:
        score = transitions = None
        if seam_nodes:
            attempts += 1
            # Routing through every crossing is something the strip can still refuse for
            # good reason -- a rung there would cross the outer boundary.  Losing the
            # whole step is worse than the painter sliding that one rung, so the crossing
            # falls back to the pre-waypoint behaviour and says so.
            print_seam_crossing_skipped(
                region,
                "waypoint",
                _waypoint_diagnostic(seam_nodes, allowed, boundary_geometry),
            )
            try:
                score, transitions = _build_transitions(
                    inner,
                    outer,
                    inner_boundary,
                    outer_boundary,
                    closed,
                    boundary_geometry,
                    region=region,
                )
                seam_nodes = ()
                complete = False
            except ValueError:
                score = transitions = None
        if transitions is None:
            # The strict sweep found no path at all: the band's wide-face budget has to
            # land somewhere and every placement re-entered.  A re-entrant corner is
            # still the lesser loss against losing the whole step, so the last sweep
            # prices one at REFLEX_PENALTY_WEIGHT instead of refusing it -- bought only
            # when nothing clean survives -- and the answer is marked degraded so it is
            # never frozen.
            attempts += 1
            reflex_reject = False
            complete = False
            try:
                score, transitions = _build_transitions(
                    inner,
                    outer,
                    inner_boundary,
                    outer_boundary,
                    closed,
                    boundary_geometry,
                    seam_nodes,
                    region=region,
                    reflex_reject=False,
                )
            except ValueError:
                raise strict_error from None
            print_reflex_fallback(
                region,
                "degraded: a wide face re-enters past 180 degrees; "
                "no clean placement survived the band's budget",
            )
    accumulate_scan("plan-build", time.perf_counter() - started, attempts)
    started = time.perf_counter()
    dp_transitions = transitions
    transitions = _beautify_transitions(
        transitions,
        inner,
        outer,
        inner_boundary,
        outer_boundary,
        closed,
        boundary_geometry,
        seam_nodes,
        reflex_reject,
    )
    accumulate_scan("plan-beautify", time.perf_counter() - started, 1)
    return transitions, score, complete, transitions != dp_transitions


def build_ordered_strip_plan(
    inner_vertices,
    outer_vertices,
    region,
    waypoints=(),
    frozen=None,
    ladders=None,
    decision=None,
):
    """Resample two ordered curves into one direct, monotone strip.

    The solve sees geometry, with two authorized exceptions.  ``waypoints`` are the ladder
    nodes :func:`.seams.region_seam_waypoints` says a seam crossing needs, and the search may
    not route around them.  The region's :data:`_PAIRING_NODES` are the rungs its own source
    band drew; those refuse no step either -- they price one, and where the pattern they
    describe needs a face the dense rail's kinds do not supply they buy the strip that kind
    (:func:`_pairing_pinches`).  What they never do is name a node the search has to stand on,
    because a band rebuilt onto fewer inner columns than the source has cannot stand on the
    recorded nodes at the face count the source drew -- what it can match is how many of them
    leave each of its columns, which is the tally :func:`_pairing_profile` counts out and
    :func:`_pairing_offset` prices.
    ``outer_vertices`` arrives in the direction :func:`outer_boundary_order` chose, because
    that is the order the seam looks its rung up in and the order the pairing nodes were
    counted in.

    ``frozen`` is the entry :func:`frozen_ladder` says this step may replay: the search
    and the local swap are skipped outright and only the two rails' coordinates move,
    which is what stops a shape axis from re-pairing a strip it was never asked to
    touch.  ``ladders`` is where a solved ladder is written back under
    ``region["region_index"]``, together with the ``decision`` the outer rail was walked
    by -- the two are one unit, since the saved transitions are indices into that order.
    A ladder that no longer fits its rails is re-solved and *does* overwrite the entry,
    so a freeze that outlived its own geometry costs one flip and then settles instead
    of costing one flip per tick.
    """
    closed = region["closed"]
    if len(inner_vertices) < (3 if closed else 2):
        raise ValueError(pgettext("The inner curve has too few points."))
    if len(outer_vertices) < (3 if closed else 2):
        raise ValueError(pgettext("The outer curve has too few points."))

    started = time.perf_counter()
    inner_boundary = parameterize_boundary(inner_vertices, closed)
    outer_boundary = parameterize_boundary(outer_vertices, closed)
    accumulate_scan("plan-parameterize", time.perf_counter() - started, 2)
    inner = inner_boundary.vertices
    outer = outer_boundary.vertices
    inner_steps = len(inner) if closed else len(inner) - 1
    outer_steps = len(outer) if closed else len(outer) - 1
    steps = (inner_steps, outer_steps)

    plan = None
    swapped = False
    source = "reuse"
    reused = frozen is not None and frozen["steps"] == steps
    if reused:
        try:
            plan = _finish_reuse(
                frozen, inner_boundary, outer_boundary, closed, inner, outer, region
            )
        except ValueError:
            plan = None
    if plan is None:
        source = "reflow" if reused else "dp"
        started = time.perf_counter()
        boundary_geometry = _prepare_boundary_geometry(
            inner_boundary.vertices,
            outer_boundary.vertices,
            closed,
        )
        accumulate_scan("plan-geometry", time.perf_counter() - started, 1)
        accumulate_scan(
            "plan-boundary-positions",
            0.0,
            len(boundary_geometry.rung_cross_cache),
        )
        pairing_nodes = tuple((region or {}).get(_PAIRING_NODES) or ())
        allowed, _budget, pinch_budget = _band_vocabulary(
            region,
            inner_steps,
            outer_steps,
        )
        (
            boundary_geometry.pairing_profile,
            pairing_counts,
        ) = _pairing_profile(
            pairing_nodes,
            inner_steps,
            outer_steps,
            closed,
        )
        boundary_geometry.pairing_doubles = (
            tuple(count >= 2 for count in pairing_counts)
            if any(count >= 2 for count in pairing_counts)
            else ()
        )
        if DIAGNOSE_LADDER and region is not None and pairing_nodes:
            print_pairing_profile(
                region,
                inner_steps,
                outer_steps,
                pairing_nodes,
                pairing_counts,
                pinch_budget,
            )
        seam_nodes, dropped_nodes = _seam_waypoint_nodes(
            tuple(waypoints),
            allowed,
            inner_steps,
            outer_steps,
        )
        if dropped_nodes:
            print_seam_crossing_skipped(
                region,
                "unreachable",
                _waypoint_reach_diagnostic(seam_nodes, dropped_nodes, allowed),
            )
        transitions, score, complete, swapped = _search_ladder(
            inner,
            outer,
            inner_boundary,
            outer_boundary,
            closed,
            boundary_geometry,
            allowed,
            seam_nodes,
            region,
        )
        plan = _ladder_plan(inner_boundary, outer_boundary, transitions, score, closed)
        _finish_ladder_plan(plan, inner, outer, region)
        if ladders is not None and decision is not None:
            if complete:
                ladders[region["region_index"]] = {
                    "steps": steps,
                    "transitions": transitions,
                    "score": score,
                    "decision": decision,
                }
            else:
                # Only a complete ladder is ever kept, and a refusal to keep one has to
                # reach the entry that is already there: leaving it would have every
                # later shape tick try it, fail it and re-solve from scratch.
                ladders.pop(region["region_index"], None)
    if DIAGNOSE_LADDER:
        print_ladder_plan(region, plan, source, swapped)
    return plan


def _finish_reuse(frozen, inner_boundary, outer_boundary, closed, inner, outer, region):
    """Rebuild a saved ladder on rails that have moved, or refuse it.

    The transitions are the only thing carried over: their faces, nodes and parameters
    are all recomputed here, so the rebuilt strip still describes the geometry it is
    actually standing on.  The score is the one the saved sequence won on the geometry
    it was solved for, which is the honest number to print beside ``reuse``.
    """
    plan = _ladder_plan(
        inner_boundary,
        outer_boundary,
        frozen["transitions"],
        frozen["score"],
        closed,
    )
    _finish_ladder_plan(plan, inner, outer, region)
    return plan
