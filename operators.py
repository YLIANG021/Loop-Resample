"""The edit-mode step engine of the Loop Resample adjust session.

``ui/interactive.py``'s wheel operator is the only caller.
"""


import bpy
import bmesh

from .core import (
    apply_ordered_strip_plan,
    apply_path_edge_attributes,
    apply_path_point_attributes,
    apply_region_edge_attributes,
    apply_region_faces,
    apply_region_seams,
    build_ordered_strip_plan,
    cleanup_detached_edges,
    detach_adjacent_strips,
    frozen_ladder,
    outer_boundary_order,
    paint_path_seam_jogs,
    rebuild_detached_path,
    rebuild_ngon_cap,
    rebuild_triangle_fan,
    region_outer_parameters,
    region_rungs,
    region_seam_rungs,
    region_seam_waypoints,
)
from .i18n import pgettext


# Wraps every refused step; the overlay strips it off before drawing the reason.  Both halves
# read it through ``pgettext``, so the strip works in translation.
FAILURE_PREFIX = "Loop Resample failed safely: "

# Said once when a gesture ends, never per step: an unmarked boundary is a fact about the
# source mesh, and the wheel rebuilds that source dozens of times a gesture.
UNMARKED_CUT_NOTE = (
    "No seam mark on {count} UV island boundary position(s), so one face there "
    "stretches across the UV map.  Mark Seam on those cuts to line them up."
)


def _failure_location(error):
    """Where an exception died, as `` (file.py:line)``, or "" when there is no traceback.

    A refused step already carries its reason.  A crash gives back ``'NoneType' object has no
    attribute 'co'``, and the notice is the only thing a user can screenshot, so the frame is
    all there is to go on.
    """
    frame = error.__traceback__
    while frame is not None and frame.tb_next is not None:
        frame = frame.tb_next
    if frame is None:
        return ""
    path = frame.tb_frame.f_code.co_filename.replace("\\", "/")
    return f" ({path.rsplit('/', 1)[-1]}:{frame.tb_lineno})"


def cut_notice(session):
    """The sentence for UV island boundaries no seam mark runs through, or "".

    ``.report`` takes one string, so this brings its own leading space rather than a second
    report; two would compete for the same popup.
    """
    count = len(session.unmarked_cuts)
    if not count:
        return ""
    return " " + pgettext(UNMARKED_CUT_NOTE).format(count=count)


def _replace_edit_bmesh(mesh, live_bm, source_bm):
    """Replace the live edit BMesh from a detached, fully evaluated copy."""
    staging_mesh = bpy.data.meshes.new("_loop_resample_staging")
    try:
        source_bm.to_mesh(staging_mesh)
        live_bm.clear()
        live_bm.from_mesh(staging_mesh)
        live_bm.normal_update()
    finally:
        bpy.data.meshes.remove(staging_mesh)
    bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=True)


def _redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


def apply_counts(context, session, counts, shape=None):
    """Resample every locked path to ``counts`` and write the result into the edit mesh.

    ``(succeeded, message)`` comes back rather than a report because the caller owns what the
    user hears: a scroll that fails at a count the planner cannot solve stays silent and leaves
    the previous mesh standing.  ``shape`` is one step's moved control points and re-weighted
    measure, or None when only counts changed.
    """
    mesh = context.active_object.data
    # Planning happens on a detached copy of the locked source, so the live mesh is untouched.
    working_bm = session.open_bmesh()
    try:
        summary = _resample(session, working_bm, counts, shape)
    except Exception as error:
        working_bm.free()
        return False, pgettext(FAILURE_PREFIX) + str(error) + _failure_location(error)

    try:
        _replace_edit_bmesh(mesh, bmesh.from_edit_mesh(mesh), working_bm)
    finally:
        working_bm.free()
    session.counts = list(counts)
    if hasattr(mesh, "update_gpu_tag"):
        mesh.update_gpu_tag()
    _redraw(context)
    return True, summary


def restore_source(context, session, counts):
    """Put the locked source back over the edit mesh, exactly as it was found.

    A cancel used to be a step at the entry counts with no shape, and a step re-solves rather
    than replays: on a ring banded 8x8 and 8x12 every vertex landed back on its source position
    and the counts matched, but 11 of the 20 rebuilt faces had different corners.  The 8x12 band
    cannot come back at all, since its source has faces the ladder may not write (one inner
    corner against three outer ones).  The pristine source is already held for every step, so
    cancel copies it back; ``counts`` is what the overlay then reads.
    """
    mesh = context.active_object.data
    pristine = session.open_bmesh()
    try:
        _replace_edit_bmesh(mesh, bmesh.from_edit_mesh(mesh), pristine)
    finally:
        pristine.free()
    session.counts = list(counts)
    if hasattr(mesh, "update_gpu_tag"):
        mesh.update_gpu_tag()
    _redraw(context)
    return True


def _resample(session, bm, counts, shape=None):
    capture = session.capture(bm)
    paths = capture["paths"]
    regions = capture["regions"]
    # Where a UV island boundary leaves the band on no rebuilt vertex.  The transfer can hand a
    # pinned vertex either copy of a split corner but cannot invent one, and only a crossing
    # puts a vertex on the cut, so a cut that never reaches the far rail gets none, marked or
    # not.  It decides nothing about the mesh; ``.seams`` holds the reading that does.
    session.unmarked_cuts = tuple(
        sorted(
            {
                index
                for region in regions
                for _, index in (region["source_faces"].get("unmarked_cuts") or ())
            }
        )
    )
    path_states = capture["path_states"]
    path_points = capture["path_points"]
    path_anchors = capture["path_anchors"]

    # The landing table says which crossings the sampler could not pin.  Rung positions still
    # come from the rails' parameters, but a refused pin leaves that search answering with the
    # nearest sample; only the table knows.
    snapshots, path_landings = session.samples(counts, path_anchors, shape=shape)

    # The copy arrived wearing the lock-time selection and the capture was the last thing that
    # read it.  Taking it off here, while its indices still name their elements, costs what the
    # user had selected; at the end it cost a pass over every element in the mesh.
    session.clear_source_selection(bm)
    detach_adjacent_strips(bm, regions)
    updated_paths = [
        rebuild_detached_path(bm, path, samples)
        for path, samples in zip(paths, snapshots)
    ]
    path_parameters = [
        session.parameters(
            index,
            updated[0],
            frame=None if shape is None else shape.frame_points(index),
        )
        for index, updated in enumerate(updated_paths)
    ]

    rebuilt_face_count = 0
    seam_landings = []
    prepared = []
    for region in regions:
        kind = region["kind"]
        inner_vertices = updated_paths[region["path_index"]][0]
        outer_vertices = (
            updated_paths[region["outer_path_index"]][0]
            if region.get("outer_path_index") is not None
            else region.get("outer_vertices")
        ) or ()
        has_ladder = kind not in {"FAN", "NGON_CAP"}
        # A phase-locked region walks its outer rail in the source's own order, so there is no
        # pairing choice to carry over and nothing a saved ladder could replay.  A counts-only
        # step (``shape is None``) always re-solves.
        ladders = (
            session.laddings
            if has_ladder and not region.get("phase_locked")
            else None
        )
        frozen = frozen_ladder(
            ladders,
            region,
            inner_vertices,
            outer_vertices,
            refresh=shape is None,
        )
        decision = None if frozen is None else frozen["decision"]
        if has_ladder:
            # A rung joins two rails walked the same way, so the order is chosen once here and
            # the seam's rung lookup, the corner transfer and the solve all read the outer rail
            # in it.  A frozen ladder brings the order it was solved against, since its
            # transitions index that order.
            outer_vertices, decision = outer_boundary_order(
                inner_vertices, outer_vertices, region, decision
            )
        inner_parameters = path_parameters[region["path_index"]]
        outer_path_index = region.get("outer_path_index")
        outer_parameters = region_outer_parameters(
            region,
            outer_vertices,
            frame_points=(
                None
                if shape is None or outer_path_index is None
                else shape.frame_points(outer_path_index)
            ),
        )
        plan = None
        if has_ladder:
            # The solve reads the two rails and takes no BMesh, so every strip is settled
            # before any face exists, and a seam can be compared with the region on the far
            # side of the same path before either is applied.
            plan = build_ordered_strip_plan(
                inner_vertices,
                outer_vertices,
                region,
                region_seam_waypoints(
                    region, path_landings, inner_parameters, outer_parameters
                ),
                frozen=frozen,
                ladders=ladders,
                decision=decision,
            )
        prepared.append(
            {
                "region": region,
                "kind": kind,
                "inner": inner_vertices,
                "outer": outer_vertices,
                "inner_parameters": inner_parameters,
                "outer_parameters": outer_parameters,
                "plan": plan,
            }
        )

    for entry in prepared:
        region = entry["region"]
        kind = entry["kind"]
        inner_vertices = entry["inner"]
        outer_vertices = entry["outer"]
        inner_parameters = entry["inner_parameters"]
        outer_parameters = entry["outer_parameters"]
        plan = entry["plan"]
        if kind == "FAN":
            rebuilt_faces = rebuild_triangle_fan(
                bm,
                inner_vertices,
                region["pole_vertex"],
                region,
                closed=region["closed"],
            )
        elif kind == "NGON_CAP":
            rebuilt_faces = rebuild_ngon_cap(bm, inner_vertices, region)
        else:
            rebuilt_faces = apply_ordered_strip_plan(bm, plan, region)
        apply_region_faces(
            bm,
            rebuilt_faces,
            region,
            inner_vertices,
            inner_parameters,
            outer_vertices,
            outer_parameters,
        )
        rungs, carried, landings = (
            region_seam_rungs(
                region, plan, inner_parameters, outer_parameters, path_landings
            )
            if plan is not None
            else ((), (), ())
        )
        seam_landings.extend(landings)
        if plan is not None:
            apply_region_seams(bm, plan, region, rungs)
        apply_region_edge_attributes(
            bm,
            region,
            inner_parameters,
            region_rungs(region, plan, inner_vertices),
            carried,
        )
        rebuilt_face_count += len(rebuilt_faces)

    apply_path_edge_attributes(updated_paths, path_parameters, path_states, bm)
    # Last, because a crossing that reached the path on two different columns joins
    # up by adding seam flags to path edges the step above already resampled.
    paint_path_seam_jogs(bm, updated_paths, seam_landings)
    apply_path_point_attributes(updated_paths, path_parameters, path_points, bm)
    cleanup_detached_edges(bm, regions)

    selected_edges = {
        edge for _, path_edges, _ in updated_paths for edge in path_edges
    }
    # Nothing else needs turning off: the source's own selection went at the top of the
    # step, and every element the rebuild created started unselected.
    for edge in selected_edges:
        edge.select_set(True)
    bm.select_history.clear()
    bm.normal_update()
    return pgettext(
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)"
    ).format(
        paths=len(paths),
        changes=", ".join(
            f"{before}->{after}"
            for before, after in zip(session.source_counts, counts)
        ),
        strips=len(regions),
        faces=rebuilt_face_count,
    )

