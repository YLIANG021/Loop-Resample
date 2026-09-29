"""Seam crossings, pinned to the ladder column they arrived on.

A crossing is a chain that cuts a band from one rail to the other.  The pool is the seam
marks the rebuild destroys plus every edge whose two faces store different UVs: an island
parts there whether anyone marked it, and ``surface`` splits its island chains on the same
rounding.  Corner colors stay out.  A color difference is a value the transfer keeps two
copies of, not a boundary a rebuilt face would straddle, and cutting on it would spend a
pinned vertex and sometimes a loaned column on a difference no island cares about.  Colors
still split chains in ``surface``; they never steer a rung here.

The band one resampled path owns is the path plus the strips on both sides, so a crossing
leaves it through a rail vertex the source already has.  That vertex survives the rebuild
and the sampler pins a sample on it, so ``region_seam_waypoints`` can hand its ladder node
to the planner as a mandatory stop.  This is the one place an attribute steers the search,
and it keeps a rebuilt face from straddling two UV islands: left to the search alone, rungs
came out a whole column off the pinned vertex.  Rail parameters are measured by projecting
each rebuilt vertex onto the source in segment-index space, so a pin on source vertex ``k``
reads back as ``k / segments`` exactly, whichever way the rail is walked.  Pins the sampler
refused are invisible to that search, so the waypoints pass also reports every crossing it
had to aim at the nearest sample instead of the promised one.

When one crossing reaches a shared path at two vertices, the strips either side can take
different columns and the red line finishes along the path's own edges, which are rebuilt
anyway.  Each rung end carries why its strip stands there (``no-slot``, ``rung-slid`` or
``pinned``); a gap between two ``pinned`` ends can only be the two rails reading one source
position as two vertices, reported as ``classification``.  Joining stretches a mark the
user already drew, so only crossings that began as marks are joined: corner values travel
everywhere, red lines stay where the user put them.
"""

from .attributes import (
    _apply_edge_state,
    _destroyed_region_edges,
    _edge_state,
    _float_edge_layers,
    _u_distance,
    merge_edge_states,
)
from .regions import region_rails
from .surface import island_boundary_edges


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
    """Every boundary chain that enters one rail of a region and leaves the other.

    A chain whose rail ends are not exactly one inner and one outer vertex cannot become a
    single rung and is left to positional matching.  Only a marked one is logged: an island
    boundary that runs along the band is the ordinary shape of an unwrapped mesh, and a line
    each would bury the ones that mean something.

    A crossing's edges stay in the region's attribute records until ``region_seam_rungs``
    gives it a rung.  Each crossing names the source edge indices it consumed so
    ``capture_region_edge_attributes``, running after this against the same BMesh, can mark
    the records those edges made.

    A fan has no outer path, so its pole is read as a one-vertex outer rail: a cut up a
    spoke leaves the band exactly there.  The inner end is what the sampler pins; without
    it no rebuilt path vertex lands on the cut and the face spanning it becomes a chord
    across the whole fan.  Only crossings reach this far.  A fan has no ladder, so the pole
    never enters a waypoint, a rung or a rail frame.
    """
    inner_vertices, outer_vertices = region_rails(region, paths)
    if not outer_vertices and region.get("kind") == "FAN":
        outer_vertices = (
            () if region.get("pole_vertex") is None else (region["pole_vertex"],)
        )
    if not inner_vertices or not outer_vertices:
        return []
    deleted = _destroyed_region_edges(region)
    marked = {edge for edge in deleted if getattr(edge, "seam", False)}
    derived = set(island_boundary_edges(deleted, bm)) - marked
    pool = [edge for edge in deleted if edge in marked or edge in derived]
    if not pool:
        # Without a log line this skip is invisible.  ``seam-kept`` names the difference:
        # seam edges the band owns but the rebuild keeps (path edges, and edges shared
        # with a face outside the band) cross no band, so no rung could stand on them.
        kept = sorted(
            {
                edge.index
                for face in region["faces"]
                if face.is_valid
                for edge in face.edges
                if getattr(edge, "seam", False)
            }
            - {edge.index for edge in deleted}
        )
        return []

    frames = region["frames"]
    inner_segments = frames["inner"]["segments"]
    outer_segments = frames["outer"]["segments"]
    inner_index = {vertex: index for index, vertex in enumerate(inner_vertices)}
    outer_index = {vertex: index for index, vertex in enumerate(outer_vertices)}
    float_layers = _float_edge_layers(bm)

    crossings = []
    for crossing_id, chain in enumerate(_seam_chains(pool)):
        chain_vertices = {vertex for edge in chain for vertex in edge.verts}
        # Part of a line the user drew?  Decides how loudly a failure speaks and whether
        # a jog along the path gets marked.
        is_marked = any(getattr(edge, "seam", False) for edge in chain)
        inner_hits = sorted(
            index for vertex, index in inner_index.items() if vertex in chain_vertices
        )
        outer_hits = sorted(
            index for vertex, index in outer_index.items() if vertex in chain_vertices
        )
        if len(inner_hits) != 1 or len(outer_hits) != 1:
            # A boundary running along the band rather than across it reaches no rung, and
            # on a mesh whose seams were never marked that is the ordinary shape of the pool.
            continue
        crossings.append(
            {
                "id": crossing_id,
                # Valid only inside the capture that made it, where both sides of the
                # lookup read the same BMesh; never resolve these against a later step.
                "source_edges": tuple(edge.index for edge in chain),
                "marked": is_marked,
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


def _pinned(path_landings, path_index, source_index):
    """Whether the sampler held one source vertex on a slot of its own.

    ``path_landings`` comes from ``ResampleSession.samples``: per locked path, ``None``
    when the step left the path standing on its own source points, otherwise the source
    indices it did pin.  A rail that is not a locked path is never resampled, so every
    one of its vertices is still itself.
    """
    if path_index is None:
        return True
    landing = path_landings[path_index]
    return landing is None or source_index in landing


def _nearest_index(parameters, target, closed):
    """The rebuilt rail vertex a captured position is closest to."""
    return min(
        range(len(parameters)),
        key=lambda index: (_u_distance(parameters[index], target, closed), index),
    )


def region_seam_waypoints(region, path_landings, inner_parameters, outer_parameters):
    """The ladder node each seam crossing needs, decided before the ladder is solved.

    The sampler pins the inner vertex onto its own source position; the outer rail is
    pinned too only where it is a locked path of its own, and an unlocked one keeps every
    vertex it started with, so both rebuilt indices are read back off the rails'
    parameters here.  Handing the pair to the search as a node its path must pass through
    keeps the rung from sliding a column off the pinned vertex: a slid rung invents a face
    with corners on two islands, and neither island holds a UV for the corner on the far
    side, so it clamps and the face collapses onto the boundary.

    This is the one place a seam reaches into the solve, and it stays a narrow exception
    to the rule that attributes do not steer geometry: it names the two vertices the
    pinning already created and asks only that they be connected.
    """
    crossings = region.get("seam_crossings") or ()
    if not crossings or not inner_parameters or not outer_parameters:
        return ()
    closed = bool(region["frames"]["closed"])
    nodes = []
    for crossing in crossings:
        nodes.append(
            (
                _nearest_index(inner_parameters, crossing["inner_u"], closed),
                _nearest_index(outer_parameters, crossing["outer_u"], closed),
            )
        )
    return tuple(nodes)


def region_seam_rungs(region, plan, inner_parameters, outer_parameters, path_landings):
    """Where each seam crossing attaches to the ladder the search already chose.

    The outer vertex has to be exact, and asking for it costs nothing: it survives the
    rebuild and every monotone ladder has a node there.  The inner column is the search's,
    so the crossing aims for the rebuilt vertex the sampler pinned and takes the nearest
    one actually offered.

    Returns ``(rungs, carried, ends)``: the nodes to paint with the flags of the chain
    they replaced; the ids of the crossings that became a rung, whose own source edges
    positional matching must no longer place; and the path vertices a *marked* crossing
    reached, which ``paint_path_seam_jogs`` joins when the strip on the far side of a path
    chose a different one.  Each end carries its cause: ``no-slot`` when the sampler
    refused to pin that source vertex at all, ``rung-slid`` when the ladder offered no
    column at the vertex the crossing named, ``pinned`` when the rung is exactly where the
    crossing asked.
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
    carried = []
    ends = []
    inner_path_index = region["path_index"]
    outer_path_index = region.get("outer_path_index")
    for crossing in crossings:
        outer_index = _nearest_index(outer_parameters, crossing["outer_u"], closed)
        candidates = columns.get(outer_index)
        if not candidates:
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
        carried.append(crossing["id"])
        # A crossing the UVs revealed rather than a mark carries no flag of its own to
        # join up with, and painting the path edges between its ends would draw a red line
        # the source never had.  Its rung still paints below.
        if crossing["marked"]:
            ends.append(
                (
                    inner_path_index,
                    crossing["inner_index"],
                    plan.inner_vertices[inner_index],
                    (
                        "no-slot"
                        if not _pinned(
                            path_landings, inner_path_index, crossing["inner_index"]
                        )
                        else "rung-slid"
                        if inner_index != preferred
                        else "pinned"
                    ),
                )
            )
            if outer_path_index is not None:
                # A rung on the outer rail never slid: the column is the one the crossing
                # names, so the only cause left is the sampler refusing to hold it.
                ends.append(
                    (
                        outer_path_index,
                        crossing["outer_index"],
                        plan.outer_vertices[outer_index],
                        "no-slot"
                        if not _pinned(
                            path_landings, outer_path_index, crossing["outer_index"]
                        )
                        else "pinned",
                    )
                )
    for rung in rungs:
        rung["state"] = merge_edge_states(rung.pop("weighted"))
    return tuple(rungs), tuple(carried), ends


def apply_region_seams(bm, plan, region, rungs):
    """Give every rung a crossing took the flags of the seam chain it replaced.

    The edge is looked up by its two endpoints rather than rediscovered from the rebuilt
    faces: the ladder node already says which pair of rail vertices this column joins, so
    there is nothing left to match.
    """
    if not rungs:
        return
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
            continue
        _apply_edge_state(edge, rung["state"], layers_by_name)


def paint_path_seam_jogs(bm, updated_paths, ends):
    """Join the two halves of a red line that reached one path at two vertices.

    ``ends`` holds ``(path index, source vertex index, rebuilt vertex, cause)`` for every
    rung end of a marked crossing that sits on a resampled path.  Both strips report the
    same source vertex, so a pair of different rebuilt vertices is one line with a gap in
    it, and the gap runs along the path's own edges.  Only the seam flag travels: crease
    and bevel values on those edges belong to the path, not to the crossing.

    One record per join, ``{path_index, source_index, landed_vertices, steps, reason}``,
    where ``landed_vertices`` numbers the path's own slots the join ran between.  The
    reason names which of three causes made the gap, and the user can only be told about
    the defect if the log says which.  ``no-slot``: the sampler refused to hold that
    source vertex on either rail, so both strips aimed at whatever vertex was nearest.
    ``rung-slid``: one strip's ladder had no rung at the vertex its crossing named; the
    planner already said so with a ``seam-skip`` line and this repeats it only as the
    consequence.  ``classification``: both strips stood on the vertex they asked for and
    still chose different ones.  A strip that never reached a rung at all reports
    ``no-column`` at itself and contributes no end here, so that name stays a skip rather
    than becoming a jog.
    """
    grouped = {}
    for path_index, source_index, vertex, cause in ends:
        by_vertex = grouped.setdefault((path_index, source_index), {})
        by_vertex.setdefault(vertex, set()).add(cause)

    joins = []
    for (path_index, source_index), by_vertex in sorted(grouped.items()):
        path_vertices = updated_paths[path_index][0]
        order = {vertex: index for index, vertex in enumerate(path_vertices)}
        touched = sorted(
            (order[vertex], causes)
            for vertex, causes in by_vertex.items()
            if vertex in order
        )
        if len(touched) < 2:
            continue
        steps = _paint_arc(
            bm,
            path_vertices,
            touched[0][0],
            touched[-1][0],
            updated_paths[path_index][2],
        )
        if steps:
            causes = set()
            for _, landed_causes in touched:
                causes |= landed_causes
            if "no-slot" in causes:
                reason = "no-slot"
            elif "rung-slid" in causes:
                reason = "rung-slid"
            else:
                reason = "classification"
            joins.append(
                {
                    "path_index": path_index,
                    "source_index": source_index,
                    "landed_vertices": [index for index, _ in touched],
                    "steps": steps,
                    "reason": reason,
                }
            )


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
