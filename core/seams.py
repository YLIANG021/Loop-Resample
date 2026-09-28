"""Seam crossings, pinned to the ladder column they arrived on.

A crossing is a chain that cuts a band from one rail to the other.  Half of what makes one
is ``edge.seam`` -- the red line the user actually sees -- and the other half is every edge
whose two faces store different UVs, because that is where a UV island parts whether or not
anyone marked it.  Both go into one pool: a cut nobody marked has to be stepped over exactly
like a marked one, and :mod:`.surface` splits its island chains on the very same rounding
(see :func:`.surface.island_boundary_edges`).  Reading the values instead of trusting the
marks is what keeps a rebuilt face inside one island on a mesh whose seams were left
unmarked -- or marked somewhere other than where the UVs change.

Colors are deliberately not in that pool.  A corner color that disagrees across an edge is a
value the transfer keeps two copies of, not a boundary a rebuilt face would straddle, and
cutting the band on it would spend a pinned vertex and sometimes a loaned column on a
difference no island cares about.  It still splits a chain in :mod:`.surface`; it never
steers a rung here.

The band one resampled path owns is the path plus the strips on both sides of it, so a
seam crossing that band leaves it through a rail vertex the source already has.  That
vertex survives the rebuild and the sampler pins a sample exactly on it, so the rung can
be required to stand on the same column: :func:`region_seam_waypoints` hands a crossing's
ladder node to :mod:`.planner` as a mandatory stop.  This is the one place an attribute
is allowed to steer the search, and it is what keeps a rebuilt face from straddling two
UV islands -- leaving the column to the search alone put rungs a whole column off the
pinned vertex.

Finding that pinned vertex again is a search of the rebuilt rail for the crossing's source
index fraction, and it is exact rather than approximate: a rail's parameters are measured by
projecting each rebuilt vertex back onto the source in *segment-index* space, so the vertex
the pin held on source vertex ``k`` reads back as ``k / segments`` -- the very number the
crossing carries -- whichever way the rail array happens to be walked.  What that search
cannot tell is that a pin was refused, so the sampler's own landing table rides along to say
so: :func:`region_seam_waypoints` reports a crossing it had to aim at the nearest sample
instead of the promised one.

The two strips either side of a path can still take different columns when one crossing
reaches the shared path at two vertices, and the red line finishes its crossing by
running along the path -- whose edges are rebuilt anyway.  Both sides aim for the vertex
the sampler pinned, so normally there is nothing to join.

When there is, the join says why: each rung end carries the reason this strip came to stand
where it does -- ``no-slot`` for a pin the sampler refused, ``rung-slid`` for a column the
ladder never offered, ``pinned`` for the vertex the crossing itself named -- and a gap
between two ends whose own causes are all ``pinned`` can only be the two rails reading one
source position as two different vertices, which is what ``classification`` reports.

What that joining does is stretch a mark the user already drew, so it stays that way: a
crossing made of unmarked edges carries no seam flag, and :func:`region_seam_rungs` offers
:func:`paint_path_seam_jogs` only the crossings that began as marks.  The corner values
travel; the red lines stay exactly where the user put them.
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
    print_landing_fallback,
    print_seam_crossing_skipped,
    print_seam_jogs,
    print_seam_rungs,
)
from .regions import _listed, region_rails
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

    The chains are drawn from two sources at once: the seam marks the rebuild destroys,
    and the edges whose two faces store different UVs.  Whichever way a cut was
    found, one that crosses the band pins the same two rail vertices.

    A chain whose two rail ends are not exactly one inner and one outer vertex
    cannot become a single rung, so it is left to positional matching rather than
    bending the ladder for.  Only a marked one says so out loud: an island boundary that
    runs along the band instead of across it is the ordinary shape of an unwrapped mesh,
    and a line each would bury the ones that mean something.

    The edges a crossing is made of stay in the region's ordinary attribute records: only a
    crossing that actually gets a rung is taken out of them, which :func:`region_seam_rungs`
    is what decides.  Each crossing names itself and the source edge indices it consumed, so
    :func:`.attributes.capture_region_edge_attributes` -- which runs after this one, against
    the same BMesh -- can mark the records those edges made.

    A fan has no outer path to read a rail from, but it does name its pole, and a
    cut that runs up a spoke leaves the band through exactly that vertex.  Read as a
    one-vertex rail it is the crossing's outer end like any other, and the inner end
    is what the sampler gets pinned: without it no rebuilt path vertex ever lands on
    the cut, and the face spanning it is drawn as a chord across the whole fan.  Only
    crossings reach this far -- a fan has no ladder, so the pole never enters a
    waypoint, a rung or a rail frame.
    """
    inner_vertices, outer_vertices = region_rails(region, paths)
    if not outer_vertices and region.get("kind") == "FAN":
        outer_vertices = (
            () if region.get("pole_vertex") is None else (region["pole_vertex"],)
        )
    if not inner_vertices or not outer_vertices:
        print_seam_crossing_skipped(
            region,
            "no-rail",
            f"kind={region.get('kind')} inner={len(inner_vertices)} "
            f"outer={len(outer_vertices)}",
        )
        return []
    deleted = _destroyed_region_edges(region)
    marked = {edge for edge in deleted if getattr(edge, "seam", False)}
    derived = set(island_boundary_edges(deleted, bm)) - marked
    pool = [edge for edge in deleted if edge in marked or edge in derived]
    if not pool:
        # A cut that is neither marked nor disagrees across this band is invisible to the
        # whole channel, and that is not something anyone can read out of a log that stays
        # quiet.  The second number names the difference: seam edges this band owns but the
        # rebuild keeps (its path edges, and any edge shared with a face outside the band)
        # cross no band at all, so there is nothing here for a rung to stand on.
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
        print_seam_crossing_skipped(
            region,
            "no-boundary",
            f"kind={region.get('kind')} deleted={len(deleted)} "
            f"seam-kept={_listed(kept)}",
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
        # Whether this chain is part of a line the user drew, which is what decides both
        # how loudly a failure speaks and whether a jog along the path gets marked.
        is_marked = any(getattr(edge, "seam", False) for edge in chain)
        inner_hits = sorted(
            index for vertex, index in inner_index.items() if vertex in chain_vertices
        )
        outer_hits = sorted(
            index for vertex, index in outer_index.items() if vertex in chain_vertices
        )
        if len(inner_hits) != 1 or len(outer_hits) != 1:
            # An island boundary that runs along the band rather than across it reaches no
            # rung, and on a mesh whose seams were never marked that is the ordinary shape
            # of the pool -- so only a line someone drew is worth a line of output.
            if is_marked:
                print_seam_crossing_skipped(
                    region,
                    "rail-ends",
                    f"inner={len(inner_hits)} outer={len(outer_hits)}",
                )
            continue
        crossings.append(
            {
                "id": crossing_id,
                # Valid only inside the capture that made it, where both sides of the
                # lookup read the same BMesh; never resolved against a later step.
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

    ``path_landings`` is what :meth:`.session.ResampleSession.samples` returns beside the
    coordinates: per locked path, ``None`` when the step left the path standing on its own
    source points, otherwise the source indices it did pin.  A rail that is not a locked
    path is never resampled, so every one of its vertices is still itself.
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

    A crossing enters the strip on one inner rail vertex and leaves on one outer one.  The
    sampler pins the inner vertex onto its own source position; the outer rail is only
    pinned too where it is a locked path of its own, and an unlocked one keeps every vertex
    it started with, so both rebuilt indices are read back off the rails' parameters here.
    Handing the pair to the search as a node its path must pass through is what keeps the
    rung from sliding a column off the pinned vertex: a slid rung invents a face with
    corners on two islands, and neither island holds a UV for the corner that ended up on
    the far side, so it clamps and the face collapses onto the boundary.

    This is the one place a seam is allowed to reach into the solve, and it stays a
    narrow exception to the rule that attributes do not steer geometry: it names the two
    vertices the pinning already created and asks only that they be connected.
    """
    crossings = region.get("seam_crossings") or ()
    if not crossings or not inner_parameters or not outer_parameters:
        return ()
    closed = bool(region["frames"]["closed"])
    inner_path_index = region["path_index"]
    outer_path_index = region.get("outer_path_index")
    nodes = []
    for crossing in crossings:
        if not _pinned(path_landings, inner_path_index, crossing["inner_index"]):
            print_landing_fallback(region, "inner", crossing["inner_index"])
        if not _pinned(path_landings, outer_path_index, crossing["outer_index"]):
            print_landing_fallback(region, "outer", crossing["outer_index"])
        nodes.append(
            (
                _nearest_index(inner_parameters, crossing["inner_u"], closed),
                _nearest_index(outer_parameters, crossing["outer_u"], closed),
            )
        )
    return tuple(nodes)


def region_seam_rungs(region, plan, inner_parameters, outer_parameters, path_landings):
    """Where each seam crossing attaches to the ladder the search already chose.

    The crossing's outer vertex is the one that has to be exact, and asking for it
    costs the search nothing: it survives the rebuild and every monotone ladder has a
    node there.  Which inner column that node is on is the search's, so the crossing
    aims for the rebuilt vertex the sampler pinned on its own source position and takes
    the nearest one that is actually offered.

    Returns ``(rungs, carried, ends)``: the nodes to paint with the flags of the chain
    they replaced, the ids of the crossings that became a rung -- whose own source
    edges positional matching must no longer place, since the rung already carries
    them -- and the path vertices a *marked* crossing reached:
    :func:`paint_path_seam_jogs` joins those when the strip on the far side of a path
    chose a different one.

    Each end carries how this strip came to stand on it, because that is the only witness
    the join has to explain itself with later: ``no-slot`` when the sampler refused to pin
    that source vertex at all, ``rung-slid`` when the ladder offered no column at the vertex
    the crossing named, and ``pinned`` when the rung is exactly where the crossing asked.
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
        carried.append(crossing["id"])
        # A crossing the UVs revealed rather than a mark carries no flag of its
        # own to join up with, and finishing it by painting the path edges between the two
        # ends would draw a red line the source never had.  Its rung still paints below.
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
                # The outer rail's column is the one the crossing names, so a rung here
                # never slid; the only way this end can be anything but the pinned vertex
                # is the sampler having refused to hold it.
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

    ``ends`` holds ``(path index, source vertex index, rebuilt vertex, cause)`` for every
    rung end of a marked crossing that sits on a resampled path.  The strips either side of
    that path report the same source vertex, so a pair of different rebuilt vertices is one
    line with a gap in it, and the gap runs along the path's own edges.  Only the seam flag
    travels -- crease and bevel values on those edges belong to the path, not to the
    crossing.

    Returns one record per line it joined, ``{path_index, source_index, landed_vertices,
    steps, reason}`` -- ``landed_vertices`` numbers the path's own slots the join ran
    between -- and prints the same.  The reason is the point: a gap between two ends
    of one crossing is a defect the user can only be told about if the log says which of
    its three causes it is.  ``no-slot`` means the sampler refused to hold that source
    vertex on either rail, so the two strips aimed at whatever vertex was nearest;
    ``rung-slid`` means one strip's ladder had no rung at the vertex its crossing named,
    which :mod:`.planner` already said out loud with a ``seam-skip`` line and this repeats
    only as the consequence; ``classification`` means both strips stood on the vertex they
    each asked for and still chose different ones, so the two readings of one position
    disagreed.  A strip that never reached a rung at all reports ``no-column`` at itself and
    contributes no end here, so that name stays a skip rather than becoming a jog.
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
    print_seam_jogs(joins)
    return tuple(joins)


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
