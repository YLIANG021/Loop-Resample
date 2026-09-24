"""Edit-mode operators for the Loop Resample adjust session."""

import time

import bpy
import bmesh

from .core import (
    apply_path_edge_attributes,
    apply_path_point_attributes,
    apply_region_edge_attributes,
    apply_region_faces,
    apply_region_seams,
    cleanup_detached_edges,
    detach_adjacent_strips,
    frozen_ladder,
    outer_boundary_order,
    paint_path_seam_jogs,
    rebuild_detached_path,
    rebuild_ngon_cap,
    rebuild_ordered_strip,
    rebuild_triangle_fan,
    region_outer_parameters,
    region_rungs,
    region_seam_rungs,
    region_seam_waypoints,
)
from .core import session as sessions
from .core.diagnostics import (
    accumulate_scan,
    mark,
    print_failure,
    print_seam_crossings,
    print_scans,
    print_timing,
    reset_scans,
    start_scope,
    start_step,
)
from .i18n import pgettext


# The one sentence every refused step is wrapped in, and the one sentence the overlay strips
# back off before drawing the reason.  Both halves read it through ``pgettext``, so the strip
# still works once the message is in another language.
FAILURE_PREFIX = "Loop Resample failed safely: "

# Said once when a gesture ends, never once per step: an unmarked UV boundary is a fact
# about the source mesh, and the wheel rebuilds that source dozens of times per gesture.
UNMARKED_CUT_NOTE = (
    "No seam mark on {count} UV island boundary position(s), so one face there "
    "stretches across the UV map.  Mark Seam on those cuts to line them up."
)


def cut_notice(session):
    """The sentence for UV island boundaries no seam mark runs through.

    ``.report`` takes one string, so this comes back with its own leading space rather
    than as a second report -- two of those would compete for the same popup.  An empty
    string is the common answer, and it leaves the caller's sentence exactly as long as
    it was before this existed.
    """
    count = len(session.unmarked_cuts)
    if not count:
        return ""
    return " " + pgettext(UNMARKED_CUT_NOTE).format(count=count)


def _replace_edit_bmesh(mesh, live_bm, source_bm):
    """Replace the live edit BMesh from a detached, fully evaluated copy."""
    started = time.perf_counter()
    staging_mesh = bpy.data.meshes.new("_loop_resample_staging")
    try:
        source_bm.to_mesh(staging_mesh)
        live_bm.clear()
        live_bm.from_mesh(staging_mesh)
        live_bm.normal_update()
    finally:
        bpy.data.meshes.remove(staging_mesh)
    bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=True)
    print_timing(
        "commit-working-bmesh",
        time.perf_counter() - started,
        verts=len(source_bm.verts),
        edges=len(source_bm.edges),
        faces=len(source_bm.faces),
    )


def _redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


class MESH_OT_loop_resample_begin(bpy.types.Operator):
    bl_idname = "mesh.loop_resample_begin"
    bl_label = pgettext("Enter Loop Resample")
    bl_description = pgettext("Lock the current mesh and selection as the resample source")

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "EDIT_MESH"
            and context.active_object is not None
            and context.active_object.type == "MESH"
            and not sessions.is_active(context)
        )

    def execute(self, context):
        try:
            session = sessions.begin(context)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        _redraw(context)
        self.report(
            {"INFO"},
            pgettext("Locked {count} path(s): {counts}").format(
                count=len(session.counts),
                counts=", ".join(str(count) for count in session.counts),
            ),
        )
        return {"FINISHED"}


class MESH_OT_loop_resample_step(bpy.types.Operator):
    bl_idname = "mesh.loop_resample_step"
    bl_label = pgettext("Loop Resample")
    bl_description = pgettext("Resample the locked paths from the session source")
    bl_options = {"UNDO"}

    delta: bpy.props.IntProperty(default=0, min=-1, max=1, options={"HIDDEN"})
    target_count: bpy.props.IntProperty(name="Target Count", default=0, min=0)
    _running = False

    @classmethod
    def poll(cls, context):
        return sessions.is_active(context) and context.mode == "EDIT_MESH"

    def invoke(self, context, event):
        if self.delta in {-1, 1} or self.target_count > 0:
            return self.execute(context)
        session = sessions.active(context)
        counts = session.counts
        self.target_count = max(counts)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "target_count")

    def execute(self, context):
        operator_type = type(self)
        if operator_type._running:
            self.report({"WARNING"}, pgettext("Mesh update is already running; wait a moment."))
            return {"CANCELLED"}
        operator_type._running = True
        try:
            session = sessions.active(context)
            if session is None:
                self.report({"ERROR"}, pgettext("Enter adjust mode first."))
                return {"CANCELLED"}
            try:
                counts = session.next_counts(self.delta, self.target_count)
            except ValueError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            succeeded, message = apply_counts(context, session, counts)
        finally:
            operator_type._running = False
        self.report(
            {"INFO" if succeeded else "ERROR"},
            message + (cut_notice(session) if succeeded else ""),
        )
        return {"FINISHED"} if succeeded else {"CANCELLED"}


def _step_request(session, counts, shape):
    """What one step was asked for, as fields for the failure line.

    Recorded before the capture as well as after it, so a raise that comes out of the
    capture itself cannot be blamed on the region that was being rebuilt.
    """
    return {
        "counts": ",".join(str(count) for count in counts),
        "source_counts": ",".join(str(count) for count in session.source_counts),
        "live_counts": ",".join(str(count) for count in session.counts),
        "closed": ",".join(str(int(value)) for value in session.closed),
        "shape": "-" if shape is None else "applied",
        "ladders": len(session.laddings),
    }


def apply_counts(context, session, counts, shape=None):
    """Resample every locked path to ``counts`` and write the result into the edit mesh.

    The stepper operator and the interactive modal both come through here, so a scroll and a
    click cannot drift apart.  ``(succeeded, message)`` comes back instead of a report
    because the caller owns what the user hears: a scroll that fails at a count the planner
    cannot solve must stay silent and leave the previous mesh standing.

    ``shape`` is one step's moved control points and re-weighted measure, or None for a
    step that only changed counts.
    """
    started = time.perf_counter()
    mesh = context.active_object.data
    start_step(**_step_request(session, counts, shape))
    # All planning happens on a detached copy of the locked source, so a
    # failure leaves the live mesh exactly as it was.
    working_bm = session.open_bmesh()
    print_timing("open-bmesh", time.perf_counter() - started)
    try:
        summary = _resample(session, working_bm, counts, shape)
    except Exception as error:
        working_bm.free()
        print_failure(time.perf_counter() - started)
        print_timing("operator-failed", time.perf_counter() - started)
        return False, pgettext(FAILURE_PREFIX) + str(error)

    try:
        _replace_edit_bmesh(mesh, bmesh.from_edit_mesh(mesh), working_bm)
    finally:
        working_bm.free()
    session.counts = list(counts)
    if hasattr(mesh, "update_gpu_tag"):
        mesh.update_gpu_tag()
    _redraw(context)
    print_timing("operator-total", time.perf_counter() - started)
    return True, summary


def restore_source(context, session, counts):
    """Put the locked source back over the edit mesh, exactly as it was found.

    A cancel used to be one more step -- the entry counts with no shape -- and a step is a
    re-solve, not a replay: measured on a ring whose bands are 8x8 and 8x12, every vertex
    landed back on its source position and the counts matched, but 11 of the 20 rebuilt
    faces had different corners.  The 8x12 band cannot be asked to come back at all,
    because its source layout has faces the ladder is not allowed to write (one inner
    corner against three outer ones), so no amount of tuning the search reaches it.

    The pristine source is already held for every step, so cancel copies it back instead
    of recomputing it.  ``counts`` is what the overlay should then read.
    """
    started = time.perf_counter()
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
    print_timing("restore-source", time.perf_counter() - started)
    return True


def _resample(session, bm, counts, shape=None):
    step_started = time.perf_counter()
    reset_scans()
    cached = session.capture_cache is not None
    mark("capture")
    capture = session.capture(bm)
    paths = capture["paths"]
    synchronized_paths = capture["synchronized"]
    regions = capture["regions"]
    # Where a UV island boundary leaves a band that no seam mark runs through.  The
    # transfer can hand a pinned vertex either copy of a split corner, but it cannot
    # invent the vertex: only a seam mark puts one on the cut.  So this comes back as a
    # sentence at the end of the gesture, and it decides nothing about the mesh -- UVs
    # stay out of the wiring, which is the whole reason the boundary is not read as one.
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
    print_timing(
        "capture-strips",
        time.perf_counter() - step_started,
        cached=cached,
        paths=len(paths),
        regions=len(regions),
        synchronized=len(synchronized_paths),
        edge_records=sum(
            len(region["edge_attributes"]["records"]) for region in regions
        ),
        face_records=sum(
            len(region["source_faces"]["records"]) for region in regions
        ),
    )

    print_seam_crossings(path_anchors, counts)
    start_step(
        **_step_request(session, counts, shape),
        paths=len(paths),
        path_vertices=",".join(str(len(path[0])) for path in paths),
        regions=len(regions),
        region_kinds="/".join(
            f"{region.get('region_index')}:{region['kind']}" for region in regions
        ),
        cached=cached,
    )
    if shape is not None:
        print(
            "[Loop Resample][diagnostic] shape "
            "tSmooth={:.2f} paths={}".format(
                shape.t_smooth,
                sum(1 for moved in shape.points if moved is not None),
            )
            + " tEven={:.2f}".format(shape.t_even)
        )
    mark("samples")
    snapshots = session.samples(counts, path_anchors, shape=shape)

    # The copy arrived wearing the selection the session was locked with, and the capture
    # was the last thing that read it.  Taking it off here, while its indices still name
    # the elements they were taken from, costs as much as the user had selected; taking it
    # off at the end used to cost a pass over every element in the mesh.
    deselect_started = time.perf_counter()
    session.clear_source_selection(bm)
    accumulate_scan(
        "deselect-all",
        time.perf_counter() - deselect_started,
        sum(len(part) for part in session.selected),
    )
    mark("detach")
    detach_adjacent_strips(bm, regions)
    mark("rebuild-paths", samples=",".join(str(len(s)) for s in snapshots))
    updated_paths = [
        rebuild_detached_path(bm, path, samples)
        for path, samples in zip(paths, snapshots)
    ]
    mark("path-parameters")
    path_parameters = [
        session.parameters(
            index,
            updated[0],
            frame=None if shape is None else shape.frame_points(index),
        )
        for index, updated in enumerate(updated_paths)
    ]
    print_timing("rebuild-target-paths", time.perf_counter() - step_started)

    rebuilt_face_count = 0
    seam_landings = []
    for region in regions:
        kind = region["kind"]
        inner_vertices = updated_paths[region["path_index"]][0]
        outer_vertices = (
            updated_paths[region["outer_path_index"]][0]
            if region.get("outer_path_index") is not None
            else region.get("outer_vertices")
        ) or ()
        has_ladder = kind not in {"FAN", "NGON_CAP"}
        # A phase-locked region walks its outer rail in the source's own order, so
        # there is no pairing choice to carry over and nothing a saved ladder could
        # replay.  ``shape is None`` is the session's baseline step -- entered first
        # and again on cancel -- and it always re-solves, which is what keeps a
        # cancelled session landing on the mesh it started from.
        ladders = (
            session.laddings
            if has_ladder and not region.get("phase_locked")
            else None
        )
        start_scope(
            region=region.get("region_index"),
            kind=kind,
            path=region["path_index"],
            outer=(
                f"path{region['outer_path_index']}"
                if region.get("outer_path_index") is not None
                else "source" if region.get("outer_vertices") else "none"
            ),
            rails=f"{len(inner_vertices)}x{len(outer_vertices)}",
            closed=int(region["closed"]),
            ladder=int(has_ladder),
            phase=int(bool(region.get("phase_locked"))),
            faces=len(region["faces"]),
            delete=len(region.get("delete_edges") or ()),
            pole=(
                getattr(region.get("pole_vertex"), "index", "-")
                if kind == "FAN"
                else "-"
            ),
        )
        frozen = frozen_ladder(
            ladders,
            region,
            inner_vertices,
            outer_vertices,
            refresh=shape is None,
        )
        decision = None if frozen is None else frozen["decision"]
        mark(
            "frozen",
            transitions="-" if frozen is None else len(frozen["transitions"]),
        )
        if has_ladder:
            # A rung has to join the two rails walked in the same direction, so
            # the choice is made once here and the seam's rung lookup, the corner
            # transfer and the solve all read the outer rail in it.  A frozen ladder
            # arrives with the order it was solved against, because its transitions
            # index that order.
            mark("outer-order")
            outer_vertices, decision = outer_boundary_order(
                inner_vertices, outer_vertices, region, decision
            )
        mark("parameters")
        region_started = time.perf_counter()
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
        accumulate_scan(
            "region-parameters", time.perf_counter() - region_started,
            len(inner_vertices) + len(outer_vertices),
        )
        mark("rebuild")
        region_started = time.perf_counter()
        plan = None
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
            rebuilt_faces, plan = rebuild_ordered_strip(
                bm,
                inner_vertices,
                outer_vertices,
                region,
                region_seam_waypoints(
                    region, inner_parameters, outer_parameters
                ),
                frozen=frozen,
                ladders=ladders,
                decision=decision,
            )
        accumulate_scan(
            "strip-rebuild", time.perf_counter() - region_started, len(rebuilt_faces)
        )
        mark("faces", rebuilt=len(rebuilt_faces))
        region_started = time.perf_counter()
        apply_region_faces(
            bm,
            rebuilt_faces,
            region,
            inner_vertices,
            inner_parameters,
            outer_vertices,
            outer_parameters,
        )
        accumulate_scan(
            "apply-face-attributes", time.perf_counter() - region_started,
            len(rebuilt_faces),
        )
        mark("region-attributes")
        region_started = time.perf_counter()
        rungs, carried, landings = (
            region_seam_rungs(region, plan, inner_parameters, outer_parameters)
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
        accumulate_scan(
            "apply-region-edge-attributes",
            time.perf_counter() - region_started,
            len(region["edge_attributes"]["records"]),
        )
        rebuilt_face_count += len(rebuilt_faces)

    start_scope(paths=len(updated_paths))
    mark("path-attributes")
    phase_started = time.perf_counter()
    apply_path_edge_attributes(updated_paths, path_parameters, path_states, bm)
    # Last, because a crossing that reached the path on two different columns joins
    # up by adding seam flags to path edges the step above already resampled.
    paint_path_seam_jogs(bm, updated_paths, seam_landings)
    apply_path_point_attributes(updated_paths, path_parameters, path_points, bm)
    accumulate_scan(
        "apply-path-attributes",
        time.perf_counter() - phase_started,
        sum(len(path) for path, _, _ in updated_paths),
    )
    mark("cleanup")
    phase_started = time.perf_counter()
    cleanup_detached_edges(bm, regions)
    accumulate_scan(
        "cleanup-edges",
        time.perf_counter() - phase_started,
        sum(len(region.get("delete_edges", ())) for region in regions),
    )

    mark("finalize")
    selected_edges = {
        edge for _, path_edges, _ in updated_paths for edge in path_edges
    }
    phase_started = time.perf_counter()
    # Nothing else needs turning off: the source's own selection went at the top of the
    # step, and every element the rebuild created started unselected.
    for edge in selected_edges:
        edge.select_set(True)
    bm.select_history.clear()
    accumulate_scan(
        "deselect-all",
        time.perf_counter() - phase_started,
        len(selected_edges),
    )
    phase_started = time.perf_counter()
    bm.normal_update()
    accumulate_scan("normal-update", time.perf_counter() - phase_started, len(bm.faces))
    print_timing(
        "rebuild-all-strips",
        time.perf_counter() - step_started,
        regions=len(regions),
        faces=rebuilt_face_count,
    )
    print_scans()
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


class MESH_OT_loop_resample_confirm(bpy.types.Operator):
    bl_idname = "mesh.loop_resample_confirm"
    bl_label = pgettext("Confirm Resample")
    bl_description = pgettext("Keep the current result and end the session")

    @classmethod
    def poll(cls, context):
        return sessions.is_active(context)

    def execute(self, context):
        sessions.end(context)
        _redraw(context)
        return {"FINISHED"}


class MESH_OT_loop_resample_cancel(bpy.types.Operator):
    bl_idname = "mesh.loop_resample_cancel"
    bl_label = pgettext("Cancel Resample")
    bl_description = pgettext("Restore the mesh to its state when the session started")
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return sessions.is_active(context) and context.mode == "EDIT_MESH"

    def execute(self, context):
        session = sessions.active(context)
        mesh = context.active_object.data
        restored_bm = session.open_bmesh()
        try:
            _replace_edit_bmesh(mesh, bmesh.from_edit_mesh(mesh), restored_bm)
        finally:
            restored_bm.free()
        if hasattr(mesh, "update_gpu_tag"):
            mesh.update_gpu_tag()
        sessions.end(context)
        _redraw(context)
        self.report({"INFO"}, pgettext("Restored the mesh from before the session."))
        return {"FINISHED"}
