"""The measure a step splits its source segments with.

The distribution axis has one direction left: evening the samples out.  It is the trick
the axis started with -- the sampler already allocates against a monotone measure along
the path, so a knob changes the measure rather than the allocator.  ``_interval_samples``
says as much in its own docstring -- ``positions`` is "any monotone measure along the
path".

What the knob may not do is move a step that lands back on zero.  The two sampler
branches do not start from the same measure today: an index-profile split weights every
source segment equally, and an anchored split already weights them by arc length.  Each
therefore gets its own baseline here, so ``even = 0`` means "the table this branch
already uses" for both of them and an untouched step stays bit-for-bit the arithmetic
that runs now.
"""

from bisect import bisect_right


_EPSILON = 1e-12


def measure_positions(lengths, even, split_by_index):
    """A cumulative measure table, or None to leave the branch's own arithmetic alone.

    ``split_by_index`` names which branch is asking: ``True`` for the index-profile
    split, whose baseline weights every source segment equally, ``False`` for the
    anchored split, which already spaces itself by arc length and so has nothing left
    to even out toward it.
    """
    if even <= 0.0 or not split_by_index or not lengths:
        return None
    # ``l ** e`` runs from every segment worth one, to every segment worth its own
    # length -- which is what makes the samples come out equally far apart.
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

    A measure table is a re-scaling of the index frame, not a new geometry: it says how
    much of the path's worth each source segment carries.  Reading it therefore means
    finding the segment the measure falls in and taking the same fraction of that
    segment's real arc length.  With the table replaced by arc length itself this is
    the identity, which is the whole reason one helper serves both branches.
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
