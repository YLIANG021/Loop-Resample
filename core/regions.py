"""Surface-region capture and source-topology mapping."""


from .paths import ordered_selected_path
from .utils import _point


def _covered_run(edges, component_edges):
    """How many of ``edges`` to drop at each end so the rest form one contiguous run.

    ``None`` means the component touches none of them, or touches two runs with a gap
    in between; cutting to the outer run would swallow surface the walk never reached.
    """
    hits = [index for index, edge in enumerate(edges) if edge in component_edges]
    if not hits:
        return None
    if hits[-1] - hits[0] + 1 != len(hits):
        return None
    return hits[0], len(edges) - 1 - hits[-1]


def _trim_proposal(paths, pair_indices, component_edges):
    """Where two rails would have to stop for the one band between them to fit.

    A band can stop short of a chain's end when two chains of different length meet
    and one runs on.  Over the span they cover the faces are a clean ladder, so
    cutting both chains to that span gives the pipeline a selection it knows how to
    rebuild.  The cut happens once, at session start, before any curve is fitted or
    index frozen, so no downstream code has to learn the user selected one edge
    more.  The tail stays as the source left it: a chain running on past the band
    keeps its last segment straight instead of following the resampled curve.
    """
    proposal = []
    for index in pair_indices:
        _, edges, closed = paths[index]
        if closed:
            return None
        run = _covered_run(edges, component_edges)
        if run is None:
            return None
        proposal.append((index, *run))
    return proposal


def region_rails(region, paths):
    """The source vertices of a region's inner and outer rails."""
    inner_vertices = paths[region["path_index"]][0]
    outer_vertices = (
        paths[region["outer_path_index"]][0]
        if region.get("outer_path_index") is not None
        else region.get("outer_vertices")
    ) or ()
    return tuple(inner_vertices), tuple(outer_vertices)


def region_frames(region, paths):
    """Frozen normalized frames for a region's two rails.

    A step moves the rails' end vertices and rebuilds everything between, so the
    source geometry is recorded once here and every capture measures against that
    record, not the live mesh.
    """
    inner_vertices, outer_vertices = region_rails(region, paths)
    closed = bool(paths[region["path_index"]][2])
    return {
        "closed": closed,
        "inner": _rail_frame(inner_vertices, closed),
        "outer": _rail_frame(outer_vertices, closed),
    }


def _rail_frame(vertices, closed):
    count = len(vertices)
    return {
        "points": tuple(_point(vertex) for vertex in vertices),
        "segments": max(count - (0 if closed else 1), 1) if count else 1,
    }


def region_source_rungs(region, paths):
    """The ``(inner, outer)`` column pairs the source band already joins with an edge.

    planner.align_outer_boundary must decide which way the two rails run against each
    other and where the ring's one cut sits.  From distances that is degenerate on a
    nearly symmetric band: both walk directions and several cut columns score within a
    few percent, so the winner moves with the sample count and the ring gets wired
    left outer to right inner.  An edge of a region face with one end on each rail
    *is* a rung of the source pairing, so the set of them answers the question
    exactly.  Indices are used because they survive the session's frozen capture and
    name the source rail's own vertices; a step hands the aligner a rail already
    resampled to another count, which planner._rungs_on_rail reconciles.
    """
    inner_vertices, outer_vertices = region_rails(region, paths)
    if not inner_vertices or not outer_vertices:
        return ()
    inner_index = {vertex.index: i for i, vertex in enumerate(inner_vertices)}
    outer_index = {vertex.index: j for j, vertex in enumerate(outer_vertices)}
    rungs = set()
    for face in region["faces"]:
        for edge in face.edges:
            first, second = edge.verts
            pair = (
                inner_index.get(first.index),
                outer_index.get(second.index),
            )
            if None not in pair:
                rungs.add(pair)
                continue
            pair = (
                inner_index.get(second.index),
                outer_index.get(first.index),
            )
            if None not in pair:
                rungs.add(pair)
    return tuple(sorted(rungs))


def _capture_ngon_cap(path_index, path, used_faces):
    """Capture a single face whose complete boundary is the selected closed path."""
    path_vertices, path_edges, is_closed = path
    if not is_closed:
        return []

    path_vertex_set = set(path_vertices)
    path_edge_set = set(path_edges)
    candidates = {
        face
        for edge in path_edges
        for face in edge.link_faces
        if face not in used_faces
        and set(face.verts) == path_vertex_set
        and set(face.edges) == path_edge_set
    }
    if len(candidates) != 1:
        return []

    face = next(iter(candidates))
    return [
        {
            "kind": "NGON_CAP",
            "path_index": path_index,
            "faces": {face},
            "delete_edges": set(),
            "outer_vertices": None,
            "outer_path_index": None,
            "closed": True,
            "normal_samples": [
                (face.calc_center_median().copy(), face.normal.copy())
            ],
            "material_index": face.material_index,
            "smooth": face.smooth,
        }
    ]


def capture_adjacent_strips(bm, paths):
    """Capture a selected rail network as disjoint adjacent surface strips.

    All selected rails are barriers during capture.  A component that touches two
    selected rails belongs to that pair; one that touches a single selected rail may
    stop at the next unselected rail, which is retained as ``outer_vertices`` and can
    be shared by two rebuilt strips, keeping two paths from claiming the same
    surface.

    Returns the regions plus the rails a band asked to be shortened,
    ``{path_index: (head, tail)}`` counted in edges of the path as handed in.  Those
    regions are left out of this pass so the caller can trim the rails and capture
    again against the shorter pair, the only way the ladder's indices stay in one
    piece.
    """
    all_path_vertices = {vertex for path in paths for vertex in path[0]}
    all_path_edges = {edge for path in paths for edge in path[1]}
    vertex_to_path = {
        vertex: path_index
        for path_index, (vertices, _, _) in enumerate(paths)
        for vertex in vertices
    }
    regions = []
    used_faces = set()
    # Where a band asked each of its two rails to stop.  A rail two bands disagree
    # about is dropped rather than guessed at, and the step then refuses as always.
    trims = {}
    trim_conflicts = set()

    # Closed n-gon caps are independent of the rail network.
    for path_index, path in enumerate(paths):
        ngon_regions = _capture_ngon_cap(path_index, path, used_faces)
        regions.extend(ngon_regions)
        used_faces.update(face for region in ngon_regions for face in region["faces"])

    def component_from_seed(seed, eligible, barriers):
        component = {seed}
        stack = [seed]
        eligible.discard(seed)
        while stack:
            face = stack.pop()
            neighbors = {
                linked_face
                for edge in face.edges
                if edge not in barriers
                for linked_face in edge.link_faces
                if linked_face in eligible
            }
            eligible.difference_update(neighbors)
            component.update(neighbors)
            stack.extend(neighbors)
        return component

    def make_outer_region(path_index, path, component):
        path_vertices, path_edges, is_closed = path
        path_vertex_set = set(path_vertices)
        path_edge_set = set(path_edges)
        component_edges = {edge for face in component for edge in face.edges}
        if component_edges & path_edge_set != path_edge_set:
            return None

        component_vertices = {vertex for face in component for vertex in face.verts}
        non_path_vertices = component_vertices - path_vertex_set
        # A fan's second rail is a single vertex, which the boundary walk below cannot
        # express: it would hand back no edges and refuse the component.  So an open
        # arc is read here too, whether the chain runs around the pole or stops short.
        # Its end spokes are shared with faces outside the region, and
        # ``cleanup_detached_edges`` leaves those alone because they are still attached.
        if len(non_path_vertices) == 1:
            pole_vertex = next(iter(non_path_vertices))
            is_triangle_fan = (
                len(component) == len(path_edges)
                and all(
                    len(face.verts) == 3
                    and pole_vertex in face.verts
                    and sum(vertex in path_vertex_set for vertex in face.verts) == 2
                    and sum(edge in path_edge_set for edge in face.edges) == 1
                    for face in component
                )
            )
            if is_triangle_fan:
                first_face = next(iter(component))
                return {
                    "kind": "FAN",
                    "path_index": path_index,
                    "faces": set(component),
                    "delete_edges": component_edges - path_edge_set,
                    "pole_vertex": pole_vertex,
                    "outer_vertices": None,
                    "outer_path_index": None,
                    "closed": is_closed,
                    "normal_samples": [
                        (face.calc_center_median().copy(), face.normal.copy())
                        for face in component
                    ],
                    "material_index": first_face.material_index,
                    "smooth": first_face.smooth,
                }

        # Only the component's outside boundary can become a fixed rail.  Edges
        # touching another selected-path vertex are endpoint/cross-rail edges.
        boundary_edges = {
            edge
            for edge in component_edges
            if sum(face in component for face in edge.link_faces) == 1
        }
        outer_edges = {
            edge
            for edge in boundary_edges
            if all(vertex not in all_path_vertices for vertex in edge.verts)
        }
        try:
            outer_vertices, ordered_outer_edges, outer_closed = ordered_selected_path(
                outer_edges
            )
        except ValueError as error:
            return None
        if outer_closed != is_closed:
            return None

        first_face = next(iter(component))
        kind = (
            "CAPPED_STRIP"
            if not is_closed and all(len(edge.link_faces) == 2 for edge in path_edges)
            else "STRIP"
        )
        return {
            "kind": kind,
            "path_index": path_index,
            "faces": set(component),
            "delete_edges": component_edges - path_edge_set - set(ordered_outer_edges),
            "outer_vertices": list(outer_vertices),
            "outer_path_index": None,
            "closed": is_closed,
            "normal_samples": [
                (face.calc_center_median().copy(), face.normal.copy())
                for face in component
            ],
            "material_index": first_face.material_index,
            "smooth": first_face.smooth,
        }

    # First capture components touching exactly one selected rail.  Faces touching
    # another selected rail are excluded from the walk, so the surface between two
    # selected rails splits into two independent strips instead of being claimed twice.
    for path_index, path in enumerate(paths):
        path_vertices, path_edges, is_closed = path
        path_vertex_set = set(path_vertices)
        path_edge_set = set(path_edges)
        endpoint_set = {path_vertices[0], path_vertices[-1]} if not is_closed else set()
        interior_vertices = path_vertex_set - endpoint_set
        other_path_vertices = all_path_vertices - path_vertex_set
        eligible = {
            face
            for face in bm.faces
            if face not in used_faces
            and any(vertex in path_vertex_set for vertex in face.verts)
            and not any(vertex in other_path_vertices for vertex in face.verts)
            and (
                any(edge in path_edge_set for edge in face.edges)
                or any(vertex in interior_vertices for vertex in face.verts)
            )
        }
        while eligible:
            seed = eligible.pop()
            component = component_from_seed(seed, eligible, all_path_edges)
            region = make_outer_region(path_index, path, component)
            if region is None:
                continue
            regions.append(region)
            used_faces.update(component)

    # Then capture faces whose vertices belong to exactly two selected rails: directly
    # adjacent rails, and for three or more, one disjoint region per neighboring pair.
    pair_faces = {}
    for face in bm.faces:
        if face in used_faces or any(vertex not in all_path_vertices for vertex in face.verts):
            continue
        path_ids = {vertex_to_path.get(vertex) for vertex in face.verts}
        path_ids.discard(None)
        if len(path_ids) != 2:
            continue
        pair_faces.setdefault(tuple(sorted(path_ids)), set()).add(face)

    for (first_index, second_index), eligible in pair_faces.items():
        first_path = paths[first_index]
        second_path = paths[second_index]
        if first_path[2] != second_path[2]:
            continue
        boundary_edges = set(first_path[1]) | set(second_path[1])
        while eligible:
            component = component_from_seed(eligible.pop(), eligible, boundary_edges)
            component_edges = {edge for face in component for edge in face.edges}
            rails = (
                (first_index, set(first_path[1])),
                (second_index, set(second_path[1])),
            )
            partial = [
                (index, rail)
                for index, rail in rails
                if component_edges & rail != rail
            ]
            proposal = (
                _trim_proposal(paths, (first_index, second_index), component_edges)
                if partial
                else None
            )
            wanted = dict(
                (index, (head, tail)) for index, head, tail in proposal or ()
            )
            if partial:
                for index, trim in wanted.items():
                    known = trims.get(index)
                    if known is not None and known != trim:
                        trim_conflicts.add(index)
                        continue
                    trims[index] = trim
                continue

            first_face = next(iter(component))
            regions.append(
                {
                    "kind": "STRIP",
                    "path_index": first_index,
                    "faces": set(component),
                    "delete_edges": component_edges - boundary_edges,
                    "outer_vertices": None,
                    "outer_path_index": second_index,
                    "closed": first_path[2],
                    "normal_samples": [
                        (face.calc_center_median().copy(), face.normal.copy())
                        for face in component
                    ],
                    "material_index": first_face.material_index,
                    "smooth": first_face.smooth,
                }
            )
            used_faces.update(component)

    for path_index, (_, path_edges, _) in enumerate(paths):
        path_edge_set = set(path_edges)
    for index in trim_conflicts:
        trims.pop(index, None)
    return regions, trims
