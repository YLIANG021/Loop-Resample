"""Seam crossings, pinned to the ladder column they arrived on.

A seam here is ``edge.seam`` -- the red line the user actually sees.  Real UV values
are deliberately not read: in Blender the two are not always in sync, and
:mod:`.surface` already keeps a rebuilt face inside one island by splitting its rail
chains where the stored corners disagree.

The band one resampled path owns is the path plus the strips on both sides of it, so a
seam crossing that band leaves it through a rail vertex the source already has.  That
vertex survives the rebuild and the sampler pins a sample exactly on it, so the rung can
be required to stand on the same column: :func:`region_seam_waypoints` hands a crossing's
ladder node to :mod:`.planner` as a mandatory stop.  This is the one place an attribute
is allowed to steer the search, and it is what keeps a rebuilt face from straddling two
UV islands -- leaving the column to the search alone put rungs a whole column off the
pinned vertex.

The two strips either side of a path can still take different columns when one crossing
reaches the shared path at two vertices, and the red line finishes its crossing by
running along the path -- whose edges are rebuilt anyway.  Both sides aim for the vertex
the sampler pinned, so normally there is nothing to join.
"""

from .attributes import (
    _apply_edge_state,
    _destroyed_region_edges,
    _edge_state,
    _float_edge_layers,
    _u_distance,
    merge_edge_states,
)
from .diagnostics import (
    print_seam_crossing_skipped,
    print_seam_jogs,
    print_seam_rungs,
)
from .regions import region_rails


def _seam_chains(edges):
    """Seam edges grouped into chains that meet at a vertex."""
    by_vertex = {}
    for edge in edges:
        for vertex in edge.verts:
            by_vertex.setdefault(vertex, set()).add(edge)
    chains = []
    remaining = set(edges)
    while remaining:
        stack = [remaining.pop()]
        chain = []
        while stack:
            edge = stack.pop()
            chain.append(edge)
            for vertex in edge.verts:
                linked = by_vertex[vertex] & remaining
                remaining -= linked
                stack.extend(linked)
        chains.append(chain)
    return chains


def region_seam_crossings(region, paths, bm):
    """Every seam chain that enters one rail of a region and leaves the other.

    A chain whose two rail ends are not exactly one inner and one outer vertex
    cannot become a single rung, so it is reported and left to positional matching
    rather than bending the ladder for.  The edges a crossing is made of stay in the
    region's ordinary attribute records: only a crossing that actually gets a rung is
    taken out of them, which :func:`region_seam_rungs` is what decides.
    """
    inner_vertices, outer_vertices = region_rails(region, paths)
    if not inner_vertices or not outer_vertices:
        return []
    pool = [
        edge
        for edge in _destroyed_region_edges(region)
        if getattr(edge, "seam", False)
    ]
    if not pool:
        return []

    frames = region["frames"]
    inner_segments = frames["inner"]["segments"]
    outer_segments = frames["outer"]["segments"]
    inner_index = {vertex: index for index, vertex in enumerate(inner_vertices)}
    outer_index = {vertex: index for index, vertex in enumerate(outer_vertices)}
    float_layers = _float_edge_layers(bm)

    crossings = []
    for chain in _seam_chains(pool):
        chain_vertices = {vertex for edge in chain for vertex in edge.verts}
        inner_hits = sorted(
            index for vertex, index in inner_index.items() if vertex in chain_vertices
        )
        outer_hits = sorted(
            index for vertex, index in outer_index.items() if vertex in chain_vertices
        )
        if len(inner_hits) != 1 or len(outer_hits) != 1:
            print_seam_crossing_skipped(
                region,
                "rail-ends",
                f"inner={len(inner_hits)} outer={len(outer_hits)}",
            )
            continue
        crossings.append(
            {
                "inner_index": inner_hits[0],
                "inner_u": inner_hits[0] / inner_segments,
                "outer_index": outer_hits[0],
                "outer_u": outer_hits[0] / outer_segments,
                "state": merge_edge_states(
                    [(1.0, _edge_state(edge, float_layers)) for edge in chain]
                ),
            }
        )
    return crossings


def _nearest_index(parameters, target, closed):
    """The rebuilt rail vertex a captured position is closest to."""
    return min(
        range(len(parameters)),
        key=lambda index: (_u_distance(parameters[index], target, closed), index),
    )


def region_seam_waypoints(region, inner_parameters, outer_parameters):
    """The ladder node each seam crossing needs, decided before the ladder is solved.

    A crossing enters the strip on one inner rail vertex and leaves on one outer one.
    The sampler pins the inner vertex exactly onto its source position and the outer
    rail is not resampled at all, so both rebuilt indices are already known here.
    Handing the pair to the search as a node its path must pass through is what keeps
    the rung from sliding a column off the pinned vertex: a slid rung invents a face
    with corners on two islands, and neither island holds a UV for the corner that
    ended up on the far side, so it clamps and the face collapses onto the boundary.

    This is the one place a seam is allowed to reach into the solve, and it stays a
    narrow exception to the rule that attributes do not steer geometry: it names the
    two vertices the pinning already created and asks only that they be connected.
    """
    crossings = region.get("seam_crossings") or ()
    if not crossings or not inner_parameters or not outer_parameters:
        return ()
    closed = bool(region["frames"]["closed"])
    return tuple(
        (
            _nearest_index(inner_parameters, crossing["inner_u"], closed),
            _nearest_index(outer_parameters, crossing["outer_u"], closed),
        )
        for crossing in crossings
    )


def region_seam_rungs(region, plan, inner_parameters, outer_parameters):
    """Where each seam crossing attaches to the ladder the search already chose.

    The crossing's outer vertex is the one that has to be exact, and asking for it
    costs the search nothing: it survives the rebuild and every monotone ladder has a
    node there.  Which inner column that node is on is the search's, so the crossing
    aims for the rebuilt vertex the sampler pinned on its own source position and takes
    the nearest one that is actually offered.

    Returns ``(rungs, pinned, ends)``: the nodes to paint with the flags of the chain
    they replaced, the source inner indices positional matching must no longer place,
    and the path vertices the red line reached -- :func:`paint_path_seam_jogs` joins
    those when the strip on the far side of a path chose a different one.
    """
    crossings = region.get("seam_crossings") or ()
    if not crossings or not inner_parameters or not outer_parameters:
        return (), (), ()
    closed = bool(region["frames"]["closed"])
    inner_count = len(plan.inner_vertices)
    outer_count = len(plan.outer_vertices)
    # Every inner column the ladder left on one outer vertex, in ladder order.
    columns = {}
    for inner_index, outer_index in plan.nodes:
        columns.setdefault(outer_index % outer_count, []).append(inner_index)

    rungs = []
    by_node = {}
    pinned = []
    ends = []
    outer_path_index = region.get("outer_path_index")
    for crossing in crossings:
        outer_index = _nearest_index(outer_parameters, crossing["outer_u"], closed)
        candidates = columns.get(outer_index)
        if not candidates:
            print_seam_crossing_skipped(region, "no-column", f"outer={outer_index}")
            continue
        preferred = _nearest_index(inner_parameters, crossing["inner_u"], closed)
        inner_index = min(
            candidates,
            key=lambda index: (
                _u_distance(
                    inner_parameters[index % inner_count],
                    crossing["inner_u"],
                    closed,
                ),
                index,
            ),
        ) % inner_count
        node = (inner_index, outer_index)
        rung = by_node.get(node)
        if rung is None:
            rung = {"node": node, "preferred": preferred, "weighted": []}
            by_node[node] = rung
            rungs.append(rung)
        rung["weighted"].append((1.0, crossing["state"]))
        pinned.append(crossing["inner_index"])
        ends.append(
            (
                region["path_index"],
                crossing["inner_index"],
                plan.inner_vertices[inner_index],
            )
        )
        if outer_path_index is not None:
            ends.append(
                (
                    outer_path_index,
                    crossing["outer_index"],
                    plan.outer_vertices[outer_index],
                )
            )
    for rung in rungs:
        rung["state"] = merge_edge_states(rung.pop("weighted"))
    return tuple(rungs), tuple(pinned), ends


def apply_region_seams(bm, plan, region, rungs):
    """Give every rung a crossing took the flags of the seam chain it replaced.

    The edge is looked up by its two endpoints rather than rediscovered from the
    rebuilt faces: the ladder node already says which pair of rail vertices this column
    joins, so there is nothing left to match.
    """
    if not rungs:
        return
    print_seam_rungs(region, rungs)
    layers_by_name = {layer.name: layer for layer in _float_edge_layers(bm)}
    inner_count = len(plan.inner_vertices)
    outer_count = len(plan.outer_vertices)
    for rung in rungs:
        inner_index, outer_index = rung["node"]
        edge = bm.edges.get(
            (
                plan.inner_vertices[inner_index % inner_count],
                plan.outer_vertices[outer_index % outer_count],
            )
        )
        if edge is None:
            print_seam_crossing_skipped(region, "missing-edge", f"node={rung['node']}")
            continue
        _apply_edge_state(edge, rung["state"], layers_by_name)


def paint_path_seam_jogs(bm, updated_paths, ends):
    """Join the two halves of a red line that reached one path at two vertices.

    ``ends`` holds ``(path index, source vertex index, rebuilt vertex)`` for every rung
    end that sits on a resampled path.  The strips either side of that path report the
    same source vertex, so a pair of different rebuilt vertices is one line with a gap
    in it, and the gap runs along the path's own edges.  Only the seam flag travels --
    crease and bevel values on those edges belong to the path, not to the crossing.
    """
    grouped = {}
    for path_index, source_index, vertex in ends:
        grouped.setdefault((path_index, source_index), set()).add(vertex)

    joins = []
    for (path_index, source_index), landed in sorted(grouped.items()):
        path_vertices = updated_paths[path_index][0]
        place_of = {vertex: index for index, vertex in enumerate(path_vertices)}
        touched = sorted(place_of[vertex] for vertex in landed if vertex in place_of)
        if len(touched) < 2:
            continue
        steps = _paint_arc(
            bm,
            path_vertices,
            touched[0],
            touched[-1],
            updated_paths[path_index][2],
        )
        if steps:
            joins.append((path_index, source_index, steps))
    print_seam_jogs(joins)


def _paint_arc(bm, vertices, first, last, closed):
    """Mark the path edges between two of its own vertices, on the shorter arc."""
    count = len(vertices)
    if closed and count - (last - first) < last - first:
        first, last = last, first
    painted = 0
    index = first
    while index != last:
        following = (index + 1) % count
        edge = bm.edges.get((vertices[index], vertices[following]))
        if edge is not None:
            edge.seam = True
            painted += 1
        index = following
    return painted
