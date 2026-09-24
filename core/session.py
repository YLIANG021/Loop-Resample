"""Frozen source snapshot shared by every step of one adjust session."""

import bmesh
import bpy

from ..i18n import pgettext

from .attributes import (
    capture_path_edge_attributes,
    capture_path_point_attributes,
    capture_region_edge_attributes,
    normalized_parameters,
)
from .curves import (
    build_catmull_rom_curve,
    sample_by_arclength,
    sample_catmull_rom_curve,
)
from .paths import selected_paths, synchronize_closed_path_phases
from .regions import (
    capture_adjacent_strips,
    region_frames,
    region_source_rungs,
)
from .seams import region_seam_crossings
from .surface import capture_region_faces
from .utils import _point


_ACTIVE = None
_ACTIVE_KEY = None
_WATCH_INTERVAL = 0.1

# The only capture outputs that name a BMesh element.  Everything else a capture
# produces is already a copied value or a plain number, so it can be handed to the
# next step as it stands.
_ELEMENT_KEYS = frozenset({"faces", "delete_edges", "outer_vertices", "pole_vertex"})
_INDEX_KEYS = frozenset(
    {
        "face_indices",
        "delete_edge_indices",
        "outer_vertex_indices",
        "pole_vertex_index",
    }
)


def _freeze_paths(paths):
    return tuple(
        (
            tuple(vertex.index for vertex in vertices),
            tuple(edge.index for edge in edges),
            bool(closed),
        )
        for vertices, edges, closed in paths
    )


def _thaw_paths(frozen, bm):
    verts = bm.verts
    edges = bm.edges
    return [
        (
            [verts[index] for index in vertex_indices],
            [edges[index] for index in edge_indices],
            closed,
        )
        for vertex_indices, edge_indices, closed in frozen
    ]


def _freeze_region(region):
    frozen = {key: value for key, value in region.items() if key not in _ELEMENT_KEYS}
    frozen["face_indices"] = tuple(face.index for face in region["faces"])
    frozen["delete_edge_indices"] = tuple(edge.index for edge in region["delete_edges"])
    outer = region["outer_vertices"]
    frozen["outer_vertex_indices"] = (
        None if outer is None else tuple(vertex.index for vertex in outer)
    )
    pole = region.get("pole_vertex")
    frozen["pole_vertex_index"] = None if pole is None else pole.index
    return frozen


def _thaw_region(frozen, bm):
    region = {key: value for key, value in frozen.items() if key not in _INDEX_KEYS}
    region["faces"] = {bm.faces[index] for index in frozen["face_indices"]}
    region["delete_edges"] = {
        bm.edges[index] for index in frozen["delete_edge_indices"]
    }
    outer = frozen["outer_vertex_indices"]
    region["outer_vertices"] = (
        None if outer is None else [bm.verts[index] for index in outer]
    )
    pole = frozen["pole_vertex_index"]
    if pole is not None:
        region["pole_vertex"] = bm.verts[pole]
    return region


def _freeze_capture(captured, bm):
    return {
        "element_counts": (len(bm.verts), len(bm.edges), len(bm.faces)),
        "paths": _freeze_paths(captured["paths"]),
        "synchronized": captured["synchronized"],
        "regions": tuple(_freeze_region(region) for region in captured["regions"]),
        "path_states": captured["path_states"],
        "path_points": captured["path_points"],
        "path_anchors": captured["path_anchors"],
    }


def _thaw_capture(cache, bm):
    return {
        "paths": _thaw_paths(cache["paths"], bm),
        "synchronized": cache["synchronized"],
        "regions": [_thaw_region(region, bm) for region in cache["regions"]],
        "path_states": cache["path_states"],
        "path_points": cache["path_points"],
        "path_anchors": cache["path_anchors"],
    }


class ResampleSession:
    """One adjust session: a locked source mesh plus its resampling curves.

    Every step rebuilds from the locked mesh instead of from the previous step,
    so attributes always transfer from the original and stepping a count down
    and back up restores it exactly.  The source is a detached BMesh rather
    than a datablock, so nothing it holds can be saved into the user's file.
    ``curves`` holds ``None`` for a path that cannot be fitted, which falls
    back to arc-length sampling of its polyline.

    A session only exists inside edit mode; leaving it restores the locked
    mesh as if the session had been cancelled.
    """

    def __init__(self, obj, source, paths):
        self.obj = obj
        self.source = source
        self.source_points = tuple(
            tuple(_point(vertex) for vertex in path[0]) for path in paths
        )
        self.closed = tuple(bool(path[2]) for path in paths)
        # How each strip's rails are paired, frozen per region for as long as its
        # ladder grid keeps its size.  The shape axes move points without being asked
        # to re-pair them; the count axis and the baseline step re-solve.  It lives here
        # rather than on a region dict because ``capture`` replays a thawed copy of the
        # captured regions every step, and it dies with the session so no wiring can
        # leak into the next one.
        self.laddings = {}
        self.source_counts = tuple(len(points) for points in self.source_points)
        self.segments = tuple(
            max(count - (0 if closed else 1), 1)
            for count, closed in zip(self.source_counts, self.closed)
        )
        self.curves = []
        for points, closed in zip(self.source_points, self.closed):
            try:
                self.curves.append(build_catmull_rom_curve(points, closed))
            except ValueError:
                self.curves.append(None)
        self.counts = list(self.source_counts)
        self.capture_cache = None

    def open_bmesh(self):
        """A fresh working copy of the locked source mesh."""
        bm = self.source.copy()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    def paths(self, bm):
        """Re-derive the locked paths on a working copy of the source mesh."""
        selected_edges = {
            edge for edge in bm.edges if edge.select and not edge.hide
        }
        paths = selected_paths(selected_edges)
        paths, synchronized = synchronize_closed_path_phases(paths)
        if tuple(len(path[0]) for path in paths) != self.source_counts or tuple(
            bool(path[2]) for path in paths
        ) != self.closed:
            raise ValueError(pgettext("The source no longer matches the locked selection."))
        return paths, synchronized

    def capture(self, bm):
        """The count-independent half of a step, computed once per session.

        Every step plans on a fresh :meth:`open_bmesh` copy of the same frozen source,
        and nothing below reads the requested counts, so the whole capture is a pure
        function of that source: only element identity differs between copies.  It is
        therefore stored as indices plus copied values and re-bound onto each step's
        elements instead of being recomputed.

        The first call freezes and thaws too, so both routes hand back the same shapes
        and a freeze/thaw bug shows up on the first press rather than the second.
        """
        cache = self.capture_cache
        if cache is None:
            cache = self.capture_cache = _freeze_capture(self._capture(bm), bm)
        elif cache["element_counts"] != (
            len(bm.verts),
            len(bm.edges),
            len(bm.faces),
        ):
            raise ValueError(pgettext("The source no longer matches the locked selection."))
        return _thaw_capture(cache, bm)

    def _capture(self, bm):
        """Run every count-independent capture against a working copy of the source."""
        paths, synchronized = self.paths(bm)
        if not paths:
            raise ValueError(
                pgettext("Select one path or multiple quad-connected parallel paths.")
            )
        regions = capture_adjacent_strips(bm, paths)
        path_states = capture_path_edge_attributes(paths, bm)
        path_points = capture_path_point_attributes(paths, bm)
        for index, region in enumerate(regions):
            region["region_index"] = index
            region["frames"] = region_frames(region, paths)
            region["source_rungs"] = region_source_rungs(region, paths)
            region["phase_locked"] = (
                region.get("outer_path_index") in synchronized
                and region.get("path_index") in synchronized
            )
        # A seam decides where the new vertices have to land: pinning the rail
        # vertices it crosses keeps the red line continuous across the rebuild, so the
        # crossings have to be known before anything is sampled.
        for region in regions:
            region["seam_crossings"] = region_seam_crossings(region, paths, bm)
        for region, edge_states in zip(
            regions, capture_region_edge_attributes(regions, paths, bm)
        ):
            region["edge_attributes"] = edge_states
        for region in regions:
            region["source_faces"] = capture_region_faces(bm, region, paths)
        path_anchors = [[] for _ in paths]
        for region in regions:
            for crossing in region["seam_crossings"]:
                path_anchors[region["path_index"]].append(crossing["inner_index"])
                outer_path_index = region.get("outer_path_index")
                if outer_path_index is not None:
                    path_anchors[outer_path_index].append(crossing["outer_index"])
        return {
            "paths": paths,
            "synchronized": frozenset(synchronized),
            "regions": regions,
            "path_states": path_states,
            "path_points": path_points,
            "path_anchors": tuple(tuple(anchors) for anchors in path_anchors),
        }

    def samples(self, counts, anchors, shape=None):
        """Resampled coordinates for every locked path at the requested counts.

        ``anchors`` holds, per path, source vertex indices that must keep a sample
        exactly on them -- the rail vertices a seam crossing runs through.

        ``shape`` is one step of the smoothing and distribution axes, or None.  A moved
        path samples from a curve refitted through its moved points rather than from
        the points themselves: every position here is read off the curve object, so
        handing over moved coordinates without moving the curve changes nothing at
        all.  A path whose source cannot be fitted keeps its polyline fallback and
        only takes the moved points, and carries no measure table -- re-weighting that
        fallback would mean changing a third sampler for a source that is already
        broken.
        """
        outputs = []
        for index, (curve, points, closed, count) in enumerate(
            zip(
                self.curves if shape is None else shape.curves,
                self.source_points,
                self.closed,
                counts,
            )
        ):
            path_anchors = tuple(anchors[index])
            if shape is not None and shape.points[index] is not None:
                points = shape.points[index]
            if curve is None:
                coordinates = sample_by_arclength(
                    points,
                    count,
                    closed,
                    forced_anchors=path_anchors,
                )
            else:
                coordinates = sample_catmull_rom_curve(
                    curve,
                    count,
                    anchors=path_anchors,
                    even=shape.t_even if shape is not None else 0.0,
                )
            outputs.append(list(coordinates))
        return outputs

    def parameters(self, path_index, vertices, frame=None):
        """Place current path vertices in the locked source's parameter frame.

        ``frame`` replaces the polyline that projection runs against, and stays the
        same length and index space as the frozen source it stands in for.  Only a
        step that moved the path's own control points has anywhere else to project to.
        """
        return normalized_parameters(
            self.source_points[path_index] if frame is None else frame,
            self.closed[path_index],
            vertices,
            self.segments[path_index],
        )

    def next_counts(self, delta, target_count):
        """Counts after one step, validated against each path's minimum."""
        counts = (
            [target_count] * len(self.counts)
            if target_count > 0
            else [count + delta for count in self.counts]
        )
        for count, closed in zip(counts, self.closed):
            minimum = 3 if closed else 2
            if count < minimum:
                raise ValueError(
                    pgettext("A {kind} path needs at least {minimum} points.").format(
                        kind=pgettext("closed" if closed else "open"), minimum=minimum
                    )
                )
        return counts

    def free(self):
        self.capture_cache = None
        if self.source is not None:
            self.source.free()
        self.source = None


def active(context):
    """The session bound to the active object's mesh, if any."""
    obj = context.active_object
    if (
        _ACTIVE is None
        or obj is None
        or obj.type != "MESH"
        or obj.data is None
        or obj.data.as_pointer() != _ACTIVE_KEY
    ):
        return None
    return _ACTIVE


def is_active(context):
    return active(context) is not None


def begin(context):
    """Lock the current mesh and selection as the session source."""
    global _ACTIVE, _ACTIVE_KEY
    obj = context.active_object
    live_bm = bmesh.from_edit_mesh(obj.data)
    selected_edges = {
        edge for edge in live_bm.edges if edge.select and not edge.hide
    }
    if not selected_edges:
        # The right-click entry reaches this from vertex select mode too, where a click
        # sets ``vert.select`` and leaves every edge flag clear.  The vertices a user
        # rang out bound exactly the edges they meant, so read them back as edges rather
        # than refusing a selection that is plainly sitting on screen.
        selected_edges = {
            edge
            for edge in live_bm.edges
            if not edge.hide and all(
                vert.select and not vert.hide for vert in edge.verts
            )
        }
    paths = selected_paths(selected_edges)
    paths, _ = synchronize_closed_path_phases(paths)
    if not paths:
        raise ValueError(
            pgettext(
                "Nothing here can be resampled.  Select a continuous chain of edges, a "
                "closed edge loop, or a row of points that edges run through."
            )
        )
    session = ResampleSession(obj, live_bm.copy(), paths)
    _release()
    _ACTIVE = session
    _ACTIVE_KEY = obj.data.as_pointer()
    if not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(
            _watch, first_interval=_WATCH_INTERVAL, persistent=True
        )
    return session


def end(context):
    """Drop the active session and release its source mesh."""
    if active(context) is None:
        return
    clear()


def discard():
    """Restore the frozen source over the mesh after edit mode ended on its own.

    There is no edit bmesh to write into at this point, so the restore goes through
    ``to_mesh`` and leaves the redraw and the undo push to whatever the user does
    next -- unlike Cancel, which runs inside edit mode and does both.
    """
    session = _ACTIVE
    if session is None or _editing(session.obj):
        return None
    restored = session.open_bmesh()
    _release()
    try:
        restored.to_mesh(session.obj.data)
        session.obj.data.update()
    except ReferenceError:
        pass
    finally:
        restored.free()
    return session


def _editing(obj):
    try:
        return obj.mode == "EDIT"
    except ReferenceError:
        return False


def _watch():
    """Self-stopping poll that ends the session as soon as edit mode does."""
    if _ACTIVE is None:
        return None
    if _editing(_ACTIVE.obj):
        return _WATCH_INTERVAL
    discard()
    return None


def _release():
    global _ACTIVE, _ACTIVE_KEY
    if _ACTIVE is not None:
        _ACTIVE.free()
    _ACTIVE = None
    _ACTIVE_KEY = None


def clear():
    """Release the session, if any; also called when the add-on unregisters."""
    _release()
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
