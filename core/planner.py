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
    print_seam_crossing_skipped,
    print_seam_excursion,
)
from .geometry import (
    _crossing_after_box_overlap,
    _segments_intersect,
    diagnose_ordered_strip_geometry,
    face_quality_cost,
    validate_ordered_strip_plan,
)
from .types import TRANSITION_ADVANCE, StripPlan
from .utils import _point, _point_view

RUNG_CONTINUITY_VECTOR_WEIGHT = 0.75
TRIANGLE_DISTRIBUTION_WEIGHT = 0.9
RUNG_LENGTH_WEIGHT = 1.2

# How far outside the band its own rail lengths give it a strip may stand in order to reach
# a seam crossing, in columns, and what one step standing there costs.  A crossing the band
# cannot land on is only reachable by lending a column to one rail and handing one back to
# the other later, which is a borrowed pair of faces -- so the search is widened by this
# much, and only for a strip that lost a crossing to the band.  The crossing itself is a
# hard filter rather than a price, so this fee buys nothing the seam asked for: it is what
# stops a pair from riding along on a local quality gain.
SEAM_EXCURSION_DEPTH = 1
SEAM_EXCURSION_STEP_COST = 0.6


def _rail_shift(kind):
    """Which way one step moves the ladder's ``d = outer - inner``, in columns.

    The band's length difference is only ever closed by steps that shift ``d``, and the
    search's pruning assumes they all shift it the same way, so that assumption is read
    off here rather than written as a kind name.
    """
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    return outer_step - inner_step


# The ladder block in ``diagnostics``: how a shape axis moved a strip's connectivity.
# Off costs nothing but the branch, and nothing below reads it to decide anything.
# Set True, with ``diagnostics.DIAGNOSTICS``, to bring the lines back.
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

    Only steps that close the length gap are in that count, so a step which opens one is
    not spread against it.  That test is what keeps a pair borrowed for a seam crossing
    from being flattened out along the strip as though the rail lengths had asked for it:
    the borrowed steps stand outside the count, and :func:`._seam_excursion_cost` is what
    charges them instead.
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


def _seam_excursion_cost(
    next_inner,
    next_outer,
    inner_steps,
    outer_steps,
    depth,
):
    """What one step standing outside the strip's own band costs.

    The band is the run of ``d = outer - inner`` the rail lengths walk through on the way
    from nothing borrowed to everything spent, so a step outside it has lent a column to one
    rail and not yet handed one back -- it is in borrowed territory for as long as it stands
    there, and every step counted here is one the strip would never have taken on its own.

    ``depth`` is what a seam crossing may borrow, and a search with nothing to reach never
    leaves the band, so this returns ``0.0`` for every strip that asks for no loan.
    """
    if depth <= 0:
        return 0.0
    final_offset = outer_steps - inner_steps
    offset = next_outer - next_inner
    if min(0, final_offset) <= offset <= max(0, final_offset):
        return 0.0
    return SEAM_EXCURSION_STEP_COST


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
                # The fold asks which way round the ring is nearer, and an open rail has no
                # way round: an advance of more than half its length is just a long step, not
                # a step back.  Folding it anyway books a conflict that no source rung drew,
                # and conflicts outrank head and shift -- so a rail too short to hold an
                # interior rung (one edge segment) is walked backwards to dodge it, shearing
                # the whole band against the neighbour that stayed forward.
                if anchor is not None and is_closed:
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
    return (
        current_inner,
        outer[(outer_index + 1) % outer_count],
        current_outer,
    )


def _advance(kind, inner_index, outer_index):
    inner_step, outer_step = TRANSITION_ADVANCE[kind]
    return inner_index + inner_step, outer_index + outer_step


def _allowed_transitions(inner_steps, outer_steps, depth=0):
    """The kinds one band's ladder may spend, in the order the search tries them.

    The dense rail's surplus is what decides the ordinary kinds, so a band whose inner rail
    is the short loop is never offered a face that spends the outer rail's column.

    ``depth`` is what a seam crossing may borrow, in columns.  Standing outside the band the
    rail lengths need takes ``d`` in a direction the strip's own surplus never moves it, so
    the loan is only affordable with a kind in each direction -- and where the lengths do
    have a say, the kind they asked for is still offered first, which leaves a strip that
    borrows nothing on the tie-breaks it had.
    """
    if inner_steps == outer_steps:
        own = ("QUAD",)
    elif inner_steps < outer_steps:
        own = ("QUAD", "OUTER_TRI")
    else:
        own = ("QUAD", "INNER_TRI")
    if depth <= 0:
        return own
    if inner_steps == outer_steps:
        # A loan has to be repaid, so a strip with no length gap borrows in both directions
        # at once: one quad becomes a triangle each way, and the two together spend what the
        # quad spent.
        return ("QUAD", "OUTER_TRI", "INNER_TRI")
    borrowed = "INNER_TRI" if "OUTER_TRI" in own else "OUTER_TRI"
    return own + (borrowed,)


def _seam_waypoint_nodes(waypoints, allowed, inner_steps, outer_steps, depth=0):
    """The crossings' rung positions the search has to route through, in ladder order.

    A ladder starts at ``d = outer - inner == 0`` and ends at the difference between the
    two rail lengths, and the one triangle kind its rails permit moves ``d`` in a single
    direction, so a crossing outside that band -- or a set of them that cannot be visited
    in that one direction -- has no path at all.  The search would spend a whole sweep
    proving it and then drop every pin in the region, so the unreachable crossings are
    pruned here instead and fall back to the rung painter sliding them.  Of the rest the
    longest runnable run wins, earliest first, which leaves an already-reachable set
    untouched: only a step the search was going to lose can come back different.

    ``depth`` widens the band by that many columns on each side, which is the same loan
    :func:`._allowed_transitions` grants the search: a crossing one column outside the band
    is reachable once the strip may stand there, and the ``chain`` rule stops applying as
    soon as the vocabulary has a kind in each direction -- both of those read the band off
    the numbers rather than the order, so a set the one-direction ladder had to split is
    kept whole.

    Returns ``(nodes, dropped)``, ``dropped`` carrying the rule that cut each position
    off so a slid rung stays traceable.
    """
    final_offset = outer_steps - inner_steps
    low = min(0, final_offset) - depth
    high = max(0, final_offset) + depth
    # An inner step is the only move that shrinks d, whether it spends one column of the
    # inner rail or two.  A QUAD-only strip is pinned to d == 0 by the band above, so
    # either direction reads the same there.  Where the vocabulary grants the strip a kind in
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


def _cached_waypoint_attempt(frozen, waypoints, inner_steps, outer_steps):
    """The promises a saved ladder was won on, handed back to the solve that replaces it.

    ``waypoints`` are what the crossings ask for *after* the shape axis moved the rails, and
    a moved rail can answer one of them with its neighbour: the pinned vertex still reads
    back as its own source fraction, but the samples around it have been re-spaced, so the
    nearest column to a crossing that sits between two vertices is a coin the moved rail
    flips.  The entry's own nodes are the columns its wiring actually routed through, so
    re-solving on them keeps the strip on the ladder it had instead of flipping it to
    whichever one the re-spaced rail happens to point at now.

    ``dropped`` is still measured against the live crossings, under the new rule ``moved``:
    a crossing the replayed wiring never promised is one the rung painter slides, and the
    line has to say which.  Nothing is renegotiated here -- a strip that lost its freeze
    gets one answer, the same one it gave when the ladder was won.
    """
    depth = frozen["depth"]
    allowed = _allowed_transitions(inner_steps, outer_steps, depth)
    nodes = frozen["waypoints"]
    dropped = tuple(
        sorted(
            (inner_index, outer_index, "moved")
            for inner_index, outer_index in set(waypoints) - set(nodes)
        )
    )
    return depth, allowed, nodes, dropped


def _surplus_names(allowed):
    """Which kinds this strip may spend a rail column with, for the seam-skip line."""
    return "+".join(kind for kind in allowed if kind != "QUAD") or "none"


def _waypoint_reach_diagnostic(nodes, dropped, allowed):
    """The pruned crossings with the rule that cut them off, for the seam-skip line.

    ``band`` says the strip can never reach that ``d = outer - inner`` whatever the other
    crossings ask for, ``chain`` that the position lost the monotone competition to the
    ones kept, ``lattice`` that it is not a rung the ladder has at all, and ``moved`` that
    the crossing only appeared after a frozen wiring had already been refused, so the
    ladder being rebuilt now is not the one that promise was weighed against.  A pruned
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
        "epsilon",
        "boundary_scale",
        "minimum",
        "cell_size",
        "buckets",
        "cell_candidate_cache",
        "rung_cross_cache",
        "boundary_records",
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
        # Every rung test reads this same square root, and a rung position is tested once per
        # plan, so taking it here rather than in the sweep keeps the exponent out of the loop.
        self.epsilon = epsilon_squared ** 0.5
        self.boundary_scale = boundary_scale
        self.minimum = minimum
        self.cell_size = cell_size
        self.buckets = buckets
        # Cell box -> the two boundaries' candidate sets, for as long as the buckets are frozen.
        self.cell_candidate_cache = {}
        self.rung_cross_cache = {}
        self.boundary_records = boundary_records


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
    epsilon = boundary_geometry.epsilon
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


def _indexed_segments(boundary_geometry, cell_ranges):
    """Return each boundary's segment indices whose cells overlap a rung box.

    One list of cells serves both rails: the box a rung sweeps is fixed by its two endpoints,
    so walking the grid once per boundary rebuilt every cell tuple and re-asked every cell a
    second time just to hear the other bucket's answer.  The list costs one allocation per rung
    and replaces the second walk, which is what the sweep spends most of its time on.

    The boxes repeat far more often than the positions do: a box is only three integer intervals,
    and neighbouring rungs of similar length fall inside the same one, so 100x200 asks 5369
    positions through 997 distinct boxes.  An answer depends on nothing but the box and the frozen
    buckets, so it is remembered for the life of the plan and the later caller iterates the very
    set the first one built.  Walking the occupied cells instead of the box was measured as the
    other way to cut this, and it loses: a real rung's box averages 12-36 cells while the two
    rails together occupy 59-154, so the box is already the smaller question.
    """
    key = tuple(cell_ranges)
    cache = boundary_geometry.cell_candidate_cache
    hits = cache.get(key)
    if hits is not None:
        return hits
    cells = [
        (x_index, y_index, z_index)
        for x_index in cell_ranges[0]
        for y_index in cell_ranges[1]
        for z_index in cell_ranges[2]
    ]
    hits = []
    for bucket in boundary_geometry.buckets:
        indices = set()
        for cell in cells:
            indices.update(bucket.get(cell, ()))
        hits.append(indices)
    hits = tuple(hits)
    cache[key] = hits
    return hits


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
    one segment and sweeps dozens of the others.  ``probes`` counts the cells a
    rung's box covers, which is what the index would be asked were every box new.
    """
    epsilon_squared = boundary_geometry.epsilon_squared
    first = boundary_geometry.inner_points[position[0]]
    second = boundary_geometry.outer_points[position[1]]
    epsilon = boundary_geometry.epsilon
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
    candidates = _indexed_segments(boundary_geometry, cell_ranges)
    for boundary_index, (segments, boxes, directions) in enumerate(
        boundary_geometry.boundary_records
    ):
        probes += cell_footprint
        for index in candidates[boundary_index]:
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


def _step_base_cost(
    face,
    inner,
    outer,
    next_inner,
    next_outer,
    inner_boundary,
    outer_boundary,
    inner_steps,
    outer_steps,
    boundary_geometry,
):
    """What one step costs, read off its own geometry alone.

    Nothing here asks how the path arrived, so both the search and the local swap memoize
    it per ``(inner, outer, kind)``.
    """
    quality = face_quality_cost(face, None)
    if quality is None:
        return None
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
    )


# Stands in for "this key has no entry yet", because a cached refusal is a legitimate
# stored value (None) that ``dict.get`` cannot tell apart from a missing key.
_NOT_CACHED = object()


def _step_cost(
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
    step_cache=None,
):
    """One step's price, memoized per ``(column pair, kind)``.

    The local swap asks for the same step from both sides of the pair it is comparing, and
    the face it would rebuild to price it is the same face either way, so the second visit
    reads the first one's number off ``step_cache``.
    """
    if step_cache is None:
        return _step_base_cost(
            face,
            inner,
            outer,
            next_inner,
            next_outer,
            inner_boundary,
            outer_boundary,
            inner_steps,
            outer_steps,
            boundary_geometry,
        )
    origin = _previous_node(kind, next_inner, next_outer)
    key = (origin[0], origin[1], kind)
    base_cost = step_cache.get(key, _NOT_CACHED)
    if base_cost is _NOT_CACHED:
        base_cost = _step_base_cost(
            face,
            inner,
            outer,
            next_inner,
            next_outer,
            inner_boundary,
            outer_boundary,
            inner_steps,
            outer_steps,
            boundary_geometry,
        )
        step_cache[key] = base_cost
    return base_cost


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
    step_cache=None,
    depth=0,
):
    """Score two adjacent transitions without rebuilding the whole strip.

    ``step_cache`` rides along with ``vector_cache``: both let the caller's two visits of
    the same step answer off the first one's arithmetic instead of rebuilding and
    re-measuring its face.
    """
    inner_index = start_inner
    outer_index = start_outer
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
        step_cost = _step_cost(
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
            step_cache,
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
        score += _seam_excursion_cost(
            next_inner,
            next_outer,
            inner_steps,
            outer_steps,
            depth,
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
    depth=0,
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
    # The swap prices the same step twice -- once with the pair in each order -- and a
    # step's own geometry answers the same either way, so one cache spans the whole pass.
    step_cache = {}
    # The corners come off the coordinates the search already read, copied once per solve,
    # instead of re-reading ``vertex.co`` for every priced face.
    inner_rail = boundary_geometry.inner_points
    outer_rail = boundary_geometry.outer_points

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
                inner_rail,
                outer_rail,
                inner_boundary,
                outer_boundary,
                inner_steps,
                outer_steps,
                is_closed,
                boundary_geometry,
                triangle_count,
                vector_cache,
                step_cache,
                depth=depth,
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
                inner_rail,
                outer_rail,
                inner_boundary,
                outer_boundary,
                inner_steps,
                outer_steps,
                is_closed,
                boundary_geometry,
                triangle_count,
                vector_cache,
                step_cache,
                depth=depth,
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
    inner_boundary,
    outer_boundary,
    is_closed,
    boundary_geometry,
    waypoints,
    allowed,
    inner_steps,
    outer_steps,
    depth=0,
):
    """One full sweep of the ladder's dynamic program: the states at the far corner.

    A quad moves inner+outer by two and a triangle by one, so diagonal d is fed by
    round d-2 (quads) then round d-1 (triangles) and a round must read every part in
    that order.  One flat dict plus a diagonal filter made every round re-scan all
    history -- ~800k dead iterations to reach ~24k live ones.

    Returns ``(states, parents, expanded)``: the far corner's states as
    ``key -> cost``, one ``key -> (parent key, kind)`` link per state ever written,
    and the number of states expanded.  A state carries no transition list of its
    own -- copying the whole run onto every candidate cost more than the geometry it
    was priced with -- so the winner's run is replayed off the parent links instead.
    Every step advances at least one column, so a layer is final by the time it is
    expanded and a link can never be rewritten from under a child that already read
    it.
    """
    triangle_count = abs(inner_steps - outer_steps)
    # What is left of the rectangle once the round structure is fixed.  Only the steps
    # that shift d one way close this strip's length gap, so d moves one way only and
    # every prefix of a completable path has to stay between the start and the goal
    # offsets.  A state outside that band is not merely lost on its own account: its
    # parents are outside too, so no surviving state is reached through it and dropping
    # it cannot reorder, reprice or retie anything.
    #
    # A seam crossing may now borrow a column, which is a step that moves d the other way,
    # so the band is what decides the pruning and not the vocabulary: the natural band plus
    # the borrowed margin on either side.  Tying this to the vocabulary instead would have
    # the widened strip search the whole rectangle -- the band is what keeps the search a
    # band -- and `depth` is 0 for every strip that lost no crossing, which is every strip
    # that ever solved without a seam pinning it.
    final_offset = outer_steps - inner_steps
    low_offset = min(0, final_offset) - depth
    high_offset = max(0, final_offset) + depth
    band_limited = depth > 0 or (
        len({_rail_shift(kind) > 0 for kind in allowed if _rail_shift(kind)}) <= 1
    )
    layers = {0: {(0, 0, None): 0.0}}
    parents = {}
    # One geometric price per (column pair, kind): the boundary checks, the face's own
    # quality and the column bookkeeping below read nothing about how the path arrived
    # here, so every predecessor of the same step reuses them.  Only the rung continuity
    # stays priced per variant, because it reads the path.
    # False marks a step no path may take at all.
    step_cache = {}
    # One rung vector per node, shared by the three reads one continuity price makes.
    vector_cache = {}
    # The two rails as coordinates rather than as mesh vertices.  Everything a priced step
    # does with a corner is subtract it and measure it, and :func:`_prepare_boundary_geometry`
    # already copied both rails once for that -- so the candidate faces are built off the
    # copy.  Going through the vertices instead read ``vertex.co`` once per corner per
    # priced face, and each of those reads hands back a fresh Vector.
    inner_rail = boundary_geometry.inner_points
    outer_rail = boundary_geometry.outer_points
    expanded = 0
    for total in range(inner_steps + outer_steps):
        tri_layer = {}
        quad_layer = {}
        for (inner_index, outer_index, previous_kind), state in layers.pop(
            total
        ).items():
            expanded += 1
            prior_cost = state
            for kind in allowed:
                advance = TRANSITION_ADVANCE[kind]
                next_inner = inner_index + advance[0]
                next_outer = outer_index + advance[1]
                if next_inner > inner_steps or next_outer > outer_steps:
                    continue
                width = advance[0] + advance[1]
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
                            inner_rail,
                            outer_rail,
                            inner_index,
                            outer_index,
                            kind,
                        )
                        base_cost = _step_base_cost(
                            face,
                            inner_rail,
                            outer_rail,
                            next_inner,
                            next_outer,
                            inner_boundary,
                            outer_boundary,
                            inner_steps,
                            outer_steps,
                            boundary_geometry,
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
                            ) + _seam_excursion_cost(
                                next_inner,
                                next_outer,
                                inner_steps,
                                outer_steps,
                                depth,
                            )
                    step_cache[cache_key] = cached
                if cached is False:
                    continue
                continuity_cost = _rung_continuity_cost(
                    boundary_geometry,
                    previous_kind,
                    inner_index,
                    outer_index,
                    next_inner,
                    next_outer,
                    vector_cache,
                )
                candidate_cost = prior_cost + cached + continuity_cost
                key = (next_inner, next_outer, kind)
                layer = quad_layer if width == 2 else tri_layer
                previous = layer.get(key)
                if previous is None or candidate_cost < previous:
                    layer[key] = candidate_cost
                    parents[key] = ((inner_index, outer_index, previous_kind), kind)
        # Each step lands in the round its own width reaches.  A key names its kind, so
        # the two rounds can never offer the same state and an update has nothing to
        # overwrite.
        for offset, layer in ((1, tri_layer), (2, quad_layer)):
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
    depth=0,
):
    """Solve the whole ladder: cheapest monotone path between two ordered rails.

    No step jumps a column -- a quad takes one of each rail and the surplus triangle one
    of its own -- so on any band whichever vertex a crossing punctured is already
    guaranteed to carry a rung once this returns -- see
    :func:`.seams.region_seam_rungs`.  That guarantee is not enough either way: the rung
    it finds can sit a column off the vertex the sampler pinned, and the face in between
    then straddles two UV islands.  ``waypoints`` are the nodes :func:`.seams` says a seam
    crossing needs, and the search may not route around them.

    ``depth`` is how far outside the band the strip's own rail lengths give it may stand to
    reach one of those nodes, and it reaches both the vocabulary and the local swap, which
    has to price the borrowed stretch the same way the search did.
    """
    inner_steps = len(inner) if is_closed else len(inner) - 1
    outer_steps = len(outer) if is_closed else len(outer) - 1
    allowed = _allowed_transitions(inner_steps, outer_steps, depth)
    states, parents, expanded = _sweep_ladder(
        inner_boundary,
        outer_boundary,
        is_closed,
        boundary_geometry,
        waypoints,
        allowed,
        inner_steps,
        outer_steps,
        depth,
    )
    accumulate_scan("plan-expand", 0.0, expanded)
    if not states:
        raise ValueError(pgettext("No valid ordered strip path was found."))
    candidates = [
        (states[key], _replay_transitions(key, parents)) for key in states
    ]
    best = min(candidates, key=lambda state: state[0])
    if DIAGNOSE_LADDER and region is not None:
        print_ladder_dp(
            region,
            inner_steps,
            outer_steps,
            allowed,
            sorted(candidates, key=lambda state: state[0])[:2],
            waypoints,
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
    the same number of columns and the saved run of transitions still names faces.  The
    entry comes back whole -- the transitions, the order they count, the loan they were
    priced under and the crossings they route through -- because a replay the geometry
    refuses has to be rebuilt on the promises that wiring was won on.

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
    """
    if region.get("phase_locked"):
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
    depth=0,
):
    """Solve the ladder: the search, then the local swap over what it chose.

    Returns ``(transitions, score, complete, swapped)``.  ``complete`` is False for the
    answer the strip is allowed to give in a degraded form: routing through every seam
    waypoint refused, so the crossings fall back to positional matching.  A degraded
    ladder is never frozen, because the seam's rung would then stay off the vertex the
    sampler pinned for as long as the shape axes were scrolled.  ``swapped`` only says
    whether the local swap rewrote what the search chose, which is a diagnostic question,
    not one the rebuild asks itself.

    ``depth`` is the loan the crossings were granted, and it goes to the local swap along
    with the search -- the swap has to price a borrowed stretch the way the sweep did or it
    would move one for free.  The degraded answer gives the loan back: with no crossing left
    to reach there is nothing a borrowed pair can be for, and that strip is solved exactly
    the way a strip without any seam ever was.
    """
    started = time.perf_counter()
    attempts = 1
    complete = True
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
            depth=depth,
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
                depth = 0
                complete = False
            except ValueError:
                score = transitions = None
        if transitions is None:
            raise strict_error from None
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
        depth,
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

    The solve sees geometry, with one authorized exception: ``waypoints`` are the ladder
    nodes :func:`.seams.region_seam_waypoints` says a seam crossing needs, and the search
    may not route around them.
    ``outer_vertices`` arrives in the direction :func:`outer_boundary_order` chose, because
    that is the order the seam looks its rung up in.

    ``frozen`` is the entry :func:`frozen_ladder` says this step may replay: the search
    and the local swap are skipped outright and only the two rails' coordinates move,
    which is what stops a shape axis from re-pairing a strip it was never asked to
    touch.  ``ladders`` is where a solved ladder is written back under
    ``region["region_index"]`` as one unit -- the transitions, the ``decision`` the outer
    rail was walked by because the saved transitions are indices into that order, the
    ``depth`` of loan they were priced under, and the ``waypoints`` they actually route
    through.  A ladder that no longer fits its rails is re-solved and *does* overwrite the
    entry, so a freeze that outlived its own geometry costs one flip and then settles
    instead of costing one flip per tick -- and that one flip is taken on the saved
    promises rather than on what the re-spaced rails answer now, which is what keeps the
    flip from moving a crossing to a neighbouring column as well as moving the wiring.
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
        allowed = _allowed_transitions(inner_steps, outer_steps)
        seam_nodes, dropped_nodes = _seam_waypoint_nodes(
            tuple(waypoints),
            allowed,
            inner_steps,
            outer_steps,
        )
        # A crossing the band refuses becomes a rung the painter slides, and a slid rung on
        # one side of a path beside a pinned one on the other is one red line joining two of
        # that path's own vertices -- which is the jog.  So the strip is offered the loan
        # before the search spends a sweep proving the narrow band cannot reach, and only
        # when the wider band actually keeps a crossing the narrow one gave up: a loan that
        # buys no node would cost this strip faces for nothing, and a strip with nothing
        # dropped is never offered one at all.  Kept and bought are compared as node *sets*,
        # not as lengths, because the wider band reorders which rungs the ladder may stand
        # on and can reach a new crossing while losing one of this band's own -- and a rung
        # the strip already pinned is worth more than one it is only being offered.
        attempts = [(0, allowed, seam_nodes, dropped_nodes, "unreachable")]
        if reused and frozen["waypoints"]:
            # The wiring this step was entitled to replay refused its geometry, but the
            # crossings it was won on are the same crossings, and the moved rails do not get
            # to renegotiate them.  So the saved node set is the one offered to the search
            # and the narrow set stays behind it as the answer this strip gave before the
            # seam asked for anything -- which also means a rebuilt ladder never spends a
            # second sweep on a loan the freeze already decided.
            attempts = [
                (
                    *_cached_waypoint_attempt(
                        frozen, tuple(waypoints), inner_steps, outer_steps
                    ),
                    "moved",
                ),
                (0, allowed, seam_nodes, dropped_nodes, "unreachable"),
            ]
        elif dropped_nodes:
            borrowed_allowed = _allowed_transitions(
                inner_steps, outer_steps, SEAM_EXCURSION_DEPTH
            )
            borrowed_nodes, borrowed_dropped = _seam_waypoint_nodes(
                tuple(waypoints),
                borrowed_allowed,
                inner_steps,
                outer_steps,
                SEAM_EXCURSION_DEPTH,
            )
            if set(seam_nodes) < set(borrowed_nodes):
                attempts.insert(
                    0,
                    (
                        SEAM_EXCURSION_DEPTH,
                        borrowed_allowed,
                        borrowed_nodes,
                        borrowed_dropped,
                        "unreachable",
                    ),
                )
            else:
                # The loan was weighed and put down, so the crossings still dropped did not
                # go because no band could reach them.  Naming that is the difference
                # between a band too narrow for the mesh and a strip that refused to pay.
                attempts[0] = (0, allowed, seam_nodes, dropped_nodes, "traded")
        for loan, loan_allowed, loan_nodes, loan_dropped, skip_reason in attempts:
            if loan:
                print_seam_excursion(
                    region,
                    f"depth={loan} "
                    + _waypoint_reach_diagnostic(
                        loan_nodes, loan_dropped, loan_allowed
                    ),
                )
            elif loan_dropped:
                # ``unreachable`` is the band's own refusal; ``moved`` is the frozen wiring
                # declining to chase a crossing that only appeared when its rails were
                # re-spaced; ``traded`` is a wider band that would have reached it at the
                # price of one this band already had.  Three different things, and a log
                # that names one of them wrongly names none of them.
                print_seam_crossing_skipped(
                    region,
                    skip_reason,
                    _waypoint_reach_diagnostic(
                        loan_nodes, loan_dropped, loan_allowed
                    ),
                )
            try:
                transitions, score, complete, swapped = _search_ladder(
                    inner,
                    outer,
                    inner_boundary,
                    outer_boundary,
                    closed,
                    boundary_geometry,
                    loan_allowed,
                    loan_nodes,
                    region,
                    loan,
                )
                plan = _ladder_plan(
                    inner_boundary, outer_boundary, transitions, score, closed
                )
                _finish_ladder_plan(plan, inner, outer, region)
            except ValueError:
                # The band was wide enough for the crossing but the geometry was not, so the
                # loan is handed back and the strip is solved the way it was before the seam
                # asked for anything.  Only a borrowed ladder can fail this way; the narrow
                # answer keeps its own exception, which is what the failure report reads.
                if not loan:
                    raise
                print_seam_crossing_skipped(
                    region,
                    "excursion",
                    f"depth={loan} nodes={len(loan_nodes)}",
                )
                continue
            break
        if ladders is not None and decision is not None:
            if complete:
                ladders[region["region_index"]] = {
                    "steps": steps,
                    "transitions": transitions,
                    "score": score,
                    "decision": decision,
                    "depth": loan,
                    "waypoints": loan_nodes,
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
