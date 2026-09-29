"""Surface-region capture and source-topology mapping."""

from collections import Counter

from .diagnostics import enabled
from .paths import ordered_selected_path
from .utils import _point


def _listed(values, limit=12):
    """A sorted, capped index list for a diagnostic line."""
    values = sorted(values)
    shown = ",".join(str(value) for value in values[:limit])
    if len(values) > limit:
        shown += f",..+{len(values) - limit}"
    return f"[{shown}]"


def _rail_histogram(component, path_edge_set):
    """How many of the path's rail edges each face of a component sits on.

    ``1x8`` is a clean strip, one face per rail edge.  Anything holding two means
    that side is coarser than the rail, which is why a component like it cannot span
    the whole path and gets rejected.
    """
    histogram = Counter(
        sum(edge in path_edge_set for edge in face.edges) for face in component
    )
    return ",".join(
        f"{holds}x{count}" for holds, count in sorted(histogram.items())
    )


def print_capture_reject(
    path_index, reason, component, path_edge_set, quiet=False, **detail
):
    """Why one side of a rail was left out of the capture."""
    if quiet or not enabled():
        return
    print(
        "[Loop Resample][diagnostic] capture-reject "
        f"path={path_index} reason={reason} "
        f"faces={len(component)} rails={_rail_histogram(component, path_edge_set)}"
        + "".join(f" {key}={value}" for key, value in detail.items())
    )


def _covered_run(edges, component_edges):
    """How many of ``edges`` to drop at each end so the rest form one contiguous run.

    ``None`` means the component touches none of them, or touches two runs with a gap in
    between.  A band that stops in the middle of its rail is not a band that ends there,
    and cutting to the outer run would silently swallow surface the walk never reached.
    """
    hits = [index for index, edge in enumerate(edges) if edge in component_edges]
    if not hits:
        return None
    if hits[-1] - hits[0] + 1 != len(hits):
        return None
    return hits[0], len(edges) - 1 - hits[-1]


def _trim_proposal(paths, pair_indices, component_edges):
    """Where two rails would have to stop for the one band between them to fit.

    A band can stop short of a chain's end -- that is what two chains of different length
    look like where one of them runs on.  Nothing else about such a pair is unusual: the
    faces are a clean ladder over the span they do cover, so cutting both chains to that
    span hands the rest of the pipeline a selection it already knows how to rebuild.  The
    cut is made once, at session start, before any curve is fitted or any index frozen, so
    no downstream code has to learn that the user selected one edge more.

    What is given up is the tail itself: it stays exactly where the source left it, so a
    chain that runs on past the band keeps its last segment straight instead of following
    the resampled curve.
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

    A step moves the rails' first and last vertices and rebuilds everything in
    between, so each rail's source geometry is recorded once here and every
    capture measures positions against that record instead of the live mesh.
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

    Which way the two rails run against each other, and where the ring's one cut sits,
    is the question :func:`.planner.align_outer_boundary` answers, and answering it from
    distances is degenerate on a band that is nearly symmetric: both walk directions and
    several cut columns score within a few percent, so the winner moves with the sample
    count and the ring gets wired left outer to right inner.

    The band the user drew answers it exactly.  An edge of a region face with one end on
    each rail *is* a rung of the source pairing, so the set of them is a description of
    the pairing rather than an opinion about it.  Indices are used because they are what
    survives the session's frozen capture -- they name the source rail's own vertices, and
    a step hands the aligner a rail already resampled to another count, which is
    :func:`.planner._rungs_on_rail`'s job to reconcile.
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


def capture_adjacent_strips(bm, paths, quiet=False):
    """Capture a selected rail network as disjoint adjacent surface strips.

    All selected rails are barriers during capture.  A component that touches
    two selected rails belongs to that pair.  A component that touches only one
    selected rail is allowed to stop at the next unselected rail; that rail is
    retained as ``outer_vertices`` and can therefore be shared by two rebuilt
    strips, which is what keeps two paths from each claiming the same surface.

    Returns the regions plus the rails that a band asked to be shortened --
    ``{path_index: (head, tail)}``, counted in edges of the path as it was handed in.
    Those regions are *not* captured here: the band is left out of this pass so the
    caller can trim the rails and capture again against the shorter pair, which is the
    only way the ladder's indices stay in one piece.  ``quiet`` holds the diagnostics
    back for that first, throwaway pass.
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
    # Where a band asked each of its two rails to stop.  A rail two bands disagree about
    # is dropped from the list rather than guessed at, and the step then refuses the way it
    # always did.
    trims = {}
    trim_conflicts = set()

    # Closed n-gon caps are independent of the rail network and remain a
    # special case.
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
            print_capture_reject(
                path_index,
                "partial-rail",
                component,
                path_edge_set,
                quiet=quiet,
                covered=f"{len(component_edges & path_edge_set)}/{len(path_edge_set)}",
                missing_edges=_listed(
                    edge.index for edge in path_edge_set - component_edges
                ),
            )
            return None

        component_vertices = {vertex for face in component for vertex in face.verts}
        non_path_vertices = component_vertices - path_vertex_set
        # A fan's second rail is a single vertex, which the boundary walk below cannot
        # express -- it would hand back no edges and refuse the whole component for it.
        # That holds whether the selected chain runs all the way around the pole or stops
        # short of it, so an open arc gets read here too: its two end spokes are shared
        # with faces outside the region, and ``cleanup_detached_edges`` leaves those alone
        # because they are still attached.
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

        # Only the outside boundary of this component can become a fixed rail.
        # Edges containing another selected-path vertex are endpoint/cross-rail
        # edges and must not be mistaken for the outer path.
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
            print_capture_reject(
                path_index,
                "outer-none"
                if not outer_edges
                else "outer-unorderable",
                component,
                path_edge_set,
                quiet=quiet,
                error=str(error),
                outer_edges=_listed(edge.index for edge in outer_edges),
                boundary=_listed(edge.index for edge in boundary_edges - outer_edges),
            )
            return None
        if outer_closed != is_closed:
            print_capture_reject(
                path_index,
                "outer-openness",
                component,
                path_edge_set,
                quiet=quiet,
                outer_closed=int(outer_closed),
                path_closed=int(is_closed),
                outer_vertices=_listed(vertex.index for vertex in outer_vertices),
            )
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

    # First capture components that touch exactly one selected rail.  Faces
    # touching another selected rail are excluded from the walk, so a fixed
    # rail between two selected rails naturally splits the surface into two
    # independent strips instead of being claimed twice.
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

    # Then capture faces whose vertices belong to exactly two selected rails.
    # This handles directly adjacent selected rails and, for three or more
    # rails, produces one disjoint region per neighboring pair.
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
            if not quiet and enabled():
                print(
                    "[Loop Resample][diagnostic] capture-reject "
                    f"path={first_index} reason=pair-openness "
                    f"between={first_index}+{second_index} "
                    f"closed={int(first_path[2])}/{int(second_path[2])} "
                    f"faces={len(eligible)}"
                )
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
            for index, rail in partial:
                print_capture_reject(
                    index,
                    "partial-rail",
                    component,
                    rail,
                    quiet=quiet,
                    between=f"{first_index}+{second_index}",
                    covered=f"{len(component_edges & rail)}/{len(rail)}",
                    missing_edges=_listed(
                        edge.index for edge in rail - component_edges
                    ),
                    trim=(
                        "-"
                        if index not in wanted
                        else "{}+{}".format(*wanted[index])
                    ),
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
        linked_faces = {face for edge in path_edges for face in edge.link_faces}
        captured_faces = {
            face
            for region in regions
            if region["path_index"] == path_index
            or region.get("outer_path_index") == path_index
            for face in region["faces"]
        }
        remaining_faces = linked_faces - captured_faces
        if remaining_faces and not quiet and enabled():
            print(
                "[Loop Resample][diagnostic] capture-incomplete "
                f"path={path_index} selected_edges={len(path_edges)} "
                f"linked_faces={len(linked_faces)} captured={len(captured_faces)} "
                f"remaining={len(remaining_faces)} "
                f"rails={_rail_histogram(remaining_faces, path_edge_set)} "
                "reason=unsupported-component-boundary"
            )
            # The operator refuses the whole step once any face is still attached to
            # the rail, so the faces worth blaming are exactly these.
            for face in sorted(remaining_faces, key=lambda item: item.index)[:12]:
                print(
                    "[Loop Resample][diagnostic] capture-uncaptured "
                    f"path={path_index} face={face.index} "
                    f"verts={_listed(vertex.index for vertex in face.verts)} "
                    f"corners={len(face.verts)} "
                    f"on_rail={sum(edge in path_edge_set for edge in face.edges)} "
                    f"rail_edges={_listed(edge.index for edge in face.edges if edge in path_edge_set)} "
                    f"other_faces={len({linked for edge in face.edges for linked in edge.link_faces}) - 1}"
                )
            if len(remaining_faces) > 12:
                print(
                    "[Loop Resample][diagnostic] capture-uncaptured "
                    f"path={path_index} ..+{len(remaining_faces) - 12} more"
                )
    for index in trim_conflicts:
        trims.pop(index, None)
    return regions, trims
