"""BMesh detach, path replacement, and face reconstruction."""

import time

import bmesh
from mathutils.geometry import tessellate_polygon

from .diagnostics import accumulate_scan
from .geometry import _plan_rungs, reference_normal as _reference_normal
from .planner import build_ordered_strip_plan
from .utils import _point


def detach_adjacent_strips(bm, regions):
    faces = {face for region in regions for face in region["faces"] if face.is_valid}
    if faces:
        bmesh.ops.delete(bm, geom=list(faces), context="FACES_ONLY")
    cleanup_detached_edges(bm, regions)


def cleanup_detached_edges(bm, regions):
    edges = {
        edge
        for region in regions
        for edge in region["delete_edges"]
        if edge.is_valid and not edge.link_faces
    }
    for edge in edges:
        if edge.is_valid:
            bm.edges.remove(edge)


def rebuild_detached_path(bm, path, samples):
    """Replace a fully detached path with one sampled directly from its source."""
    source_vertices, source_edges, is_closed = path
    source_edge_set = {edge for edge in source_edges if edge.is_valid}
    attached = sorted(
        (
            (edge.index, tuple(face.index for face in edge.link_faces))
            for edge in source_edge_set
            if edge.link_faces
        ),
        key=lambda item: item[0],
    )
    if attached:
        print(
            "[Loop Resample][diagnostic] detach-refused "
            f"closed={int(is_closed)} rail_vertices={len(source_vertices)} "
            f"rail_edges={len(source_edges)} still_attached={len(attached)} "
            "edges=["
            + ", ".join(f"{edge}:{list(faces)}" for edge, faces in attached[:12])
            + "]"
        )
        first_edge, first_faces = attached[0]
        raise ValueError(
            f"{len(attached)} of {len(source_edge_set)} rail edges still hold faces "
            f"the capture left out (edge {first_edge} holds face {first_faces[0]}): "
            "the selected path does not run between two supported strips."
        )

    removable_vertices = (
        list(source_vertices[1:]) if is_closed else list(source_vertices[1:-1])
    )
    for vertex in removable_vertices:
        remaining_edges = {
            edge for edge in vertex.link_edges if edge.is_valid and edge not in source_edge_set
        }
        if vertex.link_faces or remaining_edges:
            raise ValueError(
                "The selected path contains a branch that cannot be resampled safely."
            )

    for edge in source_edge_set:
        if edge.is_valid:
            bm.edges.remove(edge)
    for vertex in removable_vertices:
        if vertex.is_valid:
            bm.verts.remove(vertex)

    if is_closed:
        rebuilt_vertices = [source_vertices[0]]
        rebuilt_vertices[0].co = samples[0]
        rebuilt_vertices.extend(bm.verts.new(coordinate) for coordinate in samples[1:])
    else:
        rebuilt_vertices = [source_vertices[0]]
        rebuilt_vertices[0].co = samples[0]
        rebuilt_vertices.extend(bm.verts.new(coordinate) for coordinate in samples[1:-1])
        source_vertices[-1].co = samples[-1]
        rebuilt_vertices.append(source_vertices[-1])

    rebuilt_edges = []
    edge_pairs = list(zip(rebuilt_vertices, rebuilt_vertices[1:]))
    if is_closed:
        edge_pairs.append((rebuilt_vertices[-1], rebuilt_vertices[0]))
    for first, second in edge_pairs:
        if bm.edges.get((first, second)) is not None:
            raise ValueError("The target path would duplicate an existing edge.")
        edge = bm.edges.new((first, second))
        rebuilt_edges.append(edge)
    return rebuilt_vertices, rebuilt_edges, is_closed


def _new_oriented_face(bm, face_vertices, region):
    """Create one rebuilt face and turn it the way the source faces faced."""
    face = bm.faces.new(face_vertices)
    face.material_index = region["material_index"]
    face.smooth = region["smooth"]
    face.normal_update()
    reference_normal = _reference_normal(face_vertices, region)
    if (
        reference_normal is not None
        and reference_normal.length > 1e-12
        and face.normal.dot(reference_normal) < 0.0
    ):
        face.normal_flip()
    return face


def rebuild_triangle_fan(bm, boundary_vertices, pole_vertex, region):
    """Rebuild a closed triangle-fan cap around its existing pole vertex."""
    if not pole_vertex.is_valid or len(boundary_vertices) < 3:
        raise ValueError("The triangle-fan cap is no longer valid.")

    new_faces = []
    for index, first in enumerate(boundary_vertices):
        second = boundary_vertices[(index + 1) % len(boundary_vertices)]
        new_faces.append(
            _new_oriented_face(bm, (first, second, pole_vertex), region)
        )
    return new_faces


def rebuild_ngon_cap(bm, boundary_vertices, region):
    """Rebuild one validated n-gon cap from its resampled boundary."""
    if len(boundary_vertices) < 3:
        raise ValueError("An n-gon cap needs at least three boundary vertices.")

    coordinates = [_point(vertex) for vertex in boundary_vertices]
    if any(
        (coordinate - previous).length_squared <= 1e-20
        for index, coordinate in enumerate(coordinates)
        for previous in coordinates[:index]
    ):
        raise ValueError("The n-gon cap boundary contains duplicate points.")

    triangles = tessellate_polygon([coordinates])
    if len(triangles) != len(coordinates) - 2:
        raise ValueError("The n-gon cap boundary is degenerate or self-intersecting.")
    scale_squared = max(
        (
            coordinates[(index + 1) % len(coordinates)] - coordinate
        ).length_squared
        for index, coordinate in enumerate(coordinates)
    )
    triangle_coordinates = [
        tuple(
            coordinates[item] if isinstance(item, int) else item
            for item in triangle
        )
        for triangle in triangles
    ]
    if any(
        (second - first).cross(third - first).length_squared
        <= max(scale_squared * scale_squared, 1e-24) * 1e-16
        for first, second, third in triangle_coordinates
    ):
        raise ValueError("The n-gon cap would contain a degenerate triangle.")

    return [_new_oriented_face(bm, tuple(boundary_vertices), region)]


def apply_ordered_strip_plan(bm, plan, region):
    """Create the faces from a previously validated strip plan."""
    new_faces = []
    sample_count = len(region.get("normal_samples", ()))
    for face_vertices in plan.faces:
        started = time.perf_counter()
        face = bm.faces.new(face_vertices)
        face.material_index = region["material_index"]
        face.smooth = region["smooth"]
        face.normal_update()
        accumulate_scan("bmesh-new-face", time.perf_counter() - started, 1)
        started = time.perf_counter()
        reference_normal = _reference_normal(face_vertices, region)
        accumulate_scan("reference-normal", time.perf_counter() - started, sample_count)
        if (
            reference_normal is not None
            and reference_normal.length > 1e-12
            and face.normal.dot(reference_normal) < 0.0
        ):
            face.normal_flip()
        new_faces.append(face)
    return new_faces


def region_rungs(region, plan, inner_vertices):
    """Every rebuilt cross-band edge of a region, with the inner index it sits at.

    A strip's columns come from its solved ladder.  A fan has one spoke per boundary
    vertex and no ladder to solve, so its column is its vertex index; an n-gon cap
    destroys no interior edge and reports none.
    """
    if plan is not None:
        inner_count = len(plan.inner_vertices)
        return [
            (inner_index % inner_count, endpoints)
            for (inner_index, _), endpoints in zip(plan.nodes, _plan_rungs(plan))
        ]
    pole_vertex = region.get("pole_vertex")
    if pole_vertex is None:
        return []
    return [
        (index, (vertex, pole_vertex)) for index, vertex in enumerate(inner_vertices)
    ]


def rebuild_ordered_strip(
    bm,
    inner_vertices,
    outer_vertices,
    region,
    waypoints=(),
    frozen=None,
    ladders=None,
    decision=None,
):
    """Plan, validate, and apply one ordered strip reconstruction.

    The plan comes back with the faces because its ladder nodes are where the seam and
    the destroyed rungs are recorded; looking an edge up by its two endpoints beats
    rediscovering it from the faces that were just created.

    ``frozen``, ``ladders`` and ``decision`` carry the saved wiring through to the
    planner, which is the only place that knows when a ladder may be replayed and when
    it has to be solved again.
    """
    plan = build_ordered_strip_plan(
        inner_vertices,
        outer_vertices,
        region,
        waypoints=waypoints,
        frozen=frozen,
        ladders=ladders,
        decision=decision,
    )
    return apply_ordered_strip_plan(bm, plan, region), plan
