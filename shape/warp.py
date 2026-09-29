"""The measure a step splits its source segments with.

The distribution axis has one direction: evening the samples out.  The sampler already
splits against a monotone measure, so a knob changes the measure, not the allocator.

``even = 0`` hands back None and the sampler keeps its own index arithmetic: an
untouched step stays bit-for-bit what it ran before this module existed.  A pinned
vertex gets no measure of its own; it takes a slot out of whatever this produced.
"""

from bisect import bisect_right


_EPSILON = 1e-12


def measure_positions(lengths, even):
    """A cumulative measure table, or None to leave the sampler's arithmetic alone.

    Only one branch asks: the index-profile split, whose baseline weights every source
    segment equally and so has arc length left to even out toward.
    """
    if even <= 0.0 or not lengths:
        return None
    # ``length ** even`` runs from every segment worth one to every segment worth its
    # own length, which is what puts the samples equally far apart.
    weights = [length ** even for length in lengths]
    cumulative = [0.0]
    for weight in weights:
        cumulative.append(cumulative[-1] + weight)
    if any(
        following - current <= _EPSILON
        for current, following in zip(cumulative, cumulative[1:])
    ):
        return None
    return tuple(cumulative)


def measure_to_distance(control_distances, positions_table, measure):
    """Where a point sitting at ``measure`` on a re-weighted frame lands on the arc.

    The table is a re-scaling of the index frame: read it by finding the segment the
    measure falls in and taking the same fraction of that segment's real arc length.
    With arc length itself as the table this is the identity, so one helper serves
    both branches.
    """
    index = min(
        max(1, bisect_right(positions_table, measure)),
        len(positions_table) - 1,
    )
    span = positions_table[index] - positions_table[index - 1]
    factor = (
        (measure - positions_table[index - 1]) / span if span > _EPSILON else 0.0
    )
    start = control_distances[index - 1]
    return start + max(0.0, min(1.0, factor)) * (
        control_distances[index] - start
    )
