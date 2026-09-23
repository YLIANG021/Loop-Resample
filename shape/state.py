"""Curve shape and distribution: the two one-way wheel axes beside the count wheel.

Nothing here reads the mesh.  A step's points are a pure function of the frozen source
plus two strengths, so the order the axes were scrolled in cannot move a single vertex,
and a session reverted from its entry state lands back on the mesh it started from -- the
same invariant the count wheel already keeps.

Which way a rebuilt strip's rungs are paired is the one thing a session carries as
history, on purpose: a strip keeps the wiring the count wheel last solved for it, so an
axis that only moves points never re-pairs the band under it.  Smoothing and then
changing a count can therefore land on a different pairing than the other way round.

Each axis carries one function, and a tick carries it one step further whichever way
the wheel turns: Shift smooths the locked curves with a Taubin low-pass, Ctrl evens the
sampler's spacing out toward equal arc length.  There is no second property on either
axis to point at, so a strength is a plain ``[0, 1]`` rather than a signed one, and
putting an effect back is the right-click's job -- it reverts the whole session -- not
the wheel's.

A frame carries two independent halves, and each is empty until its axis is moved, so
a step with neither axis moved hands the frozen objects straight back:

``points`` / ``curves``
    where a path's control points sit, and the curve fitted through them.  Polish runs
    a Taubin low-pass over the source points.  A moved path needs its curve rebuilt,
    because the sampler reads every position from the curve object rather than from a
    caller's points, and a curve that cannot be fitted is never replaced by a fittable
    one -- a moved path falling back to polyline sampling would change its spacing
    rules on the way.

``t_even``
    how the sampler splits a path between its source segments, re-weighted from equal
    index steps toward equal arc length.  The table itself is built inside the sampler,
    which is the only place that knows which of its two branches it is in.
"""

from .smoothing import polish_points

from ..core.curves import build_catmull_rom_curve


MODE_COUNT = "COUNT"
MODE_SMOOTH = "SMOOTH"
MODE_EVEN = "EVEN"

STEP = 0.05
LIMIT = 1.0


def strengthen(strength):
    """One wheel tick along a one-way axis: one step further on, clamped at full.

    Rounded because a strength is reached by accumulation and ``0.05`` is not
    representable in binary: without it a wheel scrolled twenty times would sit at
    ``1.0000000000000002`` and the clamp at ``LIMIT`` would never read as the end.
    """
    return min(LIMIT, round(strength + STEP, 6))


class ShapeFrame:
    """One step's moved control points, rebuilt curves, and the two strengths."""

    def __init__(self, points, curves, t_even, t_smooth):
        self.points = points
        self.curves = curves
        self.t_even = t_even
        self.t_smooth = t_smooth

    def frame_points(self, path_index):
        """The polyline this path's rebuilt vertices have to be projected onto.

        Every attribute and seam lookup places a rebuilt vertex by projecting it onto a
        frame whose captured knots sit at ``index / segments``, and that only works
        because the sampler puts the vertex on the frame in the first place.  Move the
        path off its frozen polyline and the projection has to be close enough instead
        of being exact -- on a smoothed path it is not, and a seam lands a column off
        the vertex its crossing runs through.  Projecting onto the path's own moved
        frame asks only that the sample sit on its curve, which is true by construction,
        and the frame has the same point count and the same indices, so the parameter
        it returns is still the index frame the capture measured in.
        """
        moved = self.points[path_index]
        return None if moved is None else tuple(moved)


class ShapeController:
    """Builds each step's frame for one session from that session's frozen source."""

    def __init__(self, session):
        self.source_points = session.source_points
        self.closed = session.closed
        self.source_curves = session.curves

    def frame(self, t_smooth, t_even):
        """This step's frame, or None while both axes sit at zero."""
        if t_smooth == 0.0 and t_even == 0.0:
            return None
        points = []
        curves = []
        for index, (entry, is_closed) in enumerate(
            zip(self.source_points, self.closed)
        ):
            moved = _shape_points(entry, is_closed, t_smooth)
            curve = self.source_curves[index]
            if moved is not None and curve is not None:
                refitted = _refit(moved, is_closed)
                if refitted is None:
                    # This step pushed the path somewhere its own curve cannot follow.
                    # Leaving the points where they are is the only honest option: the
                    # sampler reads positions off the curve while the attribute lookup
                    # projects them onto the points, and moving one without the other
                    # would put the rebuilt vertices off their own parameter frame.
                    moved = None
                else:
                    curve = refitted
            points.append(moved)
            curves.append(curve)
        return ShapeFrame(
            tuple(points), tuple(curves), t_even, t_smooth
        )


def _refit(moved, is_closed):
    """A curve through moved control points, or None when they will not take one."""
    try:
        return build_catmull_rom_curve(moved, is_closed)
    except ValueError:
        return None


def _shape_points(entry, is_closed, t_smooth):
    """``Taubin(entry)``, or None at zero strength.

    A ring is smoothed like any other path: a neighbour average has no use for ends.
    That the one remaining axis needs no closed-path exception of its own is the whole
    reason it is the only one left.
    """
    if t_smooth == 0.0:
        return None
    return tuple(polish_points(entry, is_closed, t_smooth))
