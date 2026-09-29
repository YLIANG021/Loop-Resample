"""Frozen source snapshot shared by every step of one adjust session."""

import bmesh

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

# The only capture outputs that name a BMesh element; everything else a capture produces
# is a copied value or a plain number and passes to the next step as it stands.
_ELEMENT_KEYS = frozenset({"faces", "delete_edges", "outer_vertices", "pole_vertex"})
_INDEX_KEYS = frozenset(
    {
        "face_indices",
        "delete_edge_indices",
        "outer_vertex_indices",
        "pole_vertex_index",
    }
)


def _apply_trims(paths, trims):
    """Cut each rail down to the span the band between two chains actually covers.

    Two chains of different length leave the surface between them short of one chain's
    end.  The capture reports how far each chain has to stop; cutting them there happens
    before any curve is fitted or any count frozen, so every index downstream is built on
    the shortened rail and none of them has to know a cut happened.  The dropped tail
    stays plain mesh.
    """
    if not trims:
        return paths
    trimmed = []
    for index, path in enumerate(paths):
        trim = trims.get(index)
        if trim is None or trim == (0, 0):
            trimmed.append(path)
            continue
        vertices, edges, closed = path
        head, tail = trim
        if closed or len(vertices) - head - tail < 2:
            raise ValueError(pgettext("The source no longer matches the locked selection."))
        trimmed.append(
            (
                list(vertices[head : len(vertices) - tail]),
                list(edges[head : len(edges) - tail]),
                closed,
            )
        )
    return trimmed


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


def _selected_indices(bm):
    """What is selected on a mesh, as indices into its verts, edges and faces.

    Taken once off the locked source, which keeps the flags themselves: a cancel hands
    that mesh back and the user's selection is part of what they get back.  The indices
    let a step undo the same flags on its own copy by name instead of walking all 126,000
    elements of it to find the few hundred that are set.
    """
    return (
        tuple(vertex.index for vertex in bm.verts if vertex.select),
        tuple(edge.index for edge in bm.edges if edge.select),
        tuple(face.index for face in bm.faces if face.select),
    )


class ResampleSession:
    """One adjust session: a locked source mesh plus its resampling curves.

    Every step rebuilds from the locked mesh instead of the previous step, so attributes
    always transfer from the original and stepping a count down and back up restores it
    exactly.  The source is a detached BMesh, not a datablock, so nothing it holds can be
    saved into the user's file.  ``curves`` holds ``None`` for a path that cannot be
    fitted, which falls back to arc-length sampling of its polyline.  A session only
    exists inside edit mode; leaving it restores the locked mesh as if cancelled.
    """

    def __init__(self, obj, source, paths, trims=None):
        self.obj = obj
        self.source = source
        self.selected = _selected_indices(source)
        # Paths are re-derived from the selection every step, so the trims must cut back
        # the same way each time or the paths stop matching the curves fitted below.
        self.trims = dict(trims or {})
        self.source_points = tuple(
            tuple(_point(vertex) for vertex in path[0]) for path in paths
        )
        self.closed = tuple(bool(path[2]) for path in paths)
        # Each strip's frozen wiring as one unit: how its rails are paired, the transitions
        # that pairing was solved into, the loan they were priced under and the crossings
        # they route through.  The shape axes move points without re-pairing them; the
        # count axis and the baseline step re-solve.  Lives on the session, not a region
        # dict, because ``capture`` replays a thawed copy of the regions every step; dies
        # with the session so no wiring leaks into the next one.
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
        # Vertices where a UV island boundary leaves the band on no rebuilt vertex at all.
        # Written by the capture, read only to word the closing report; it steers no
        # geometry, which is why it lives here and not in the sampler.
        self.unmarked_cuts = ()

    def open_bmesh(self):
        """A fresh working copy of the locked source mesh."""
        bm = self.source.copy()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    def clear_source_selection(self, bm):
        """Undo the locked selection on a working copy of the source.

        Has to run after the capture, which is the last thing that reads a selection, and
        before the detach: the detach deletes faces and edges and leaves bmesh renumbering
        around the holes, so these indices stop naming the elements they were taken from.
        Nothing the rebuild creates is born selected, so this and the path edges a step
        selects at the end are its whole selection: the same set the three full-mesh
        passes used to arrive at.
        """
        vertices, edges, faces = self.selected
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        for index in vertices:
            bm.verts[index].select_set(False)
        for index in edges:
            bm.edges[index].select_set(False)
        for index in faces:
            bm.faces[index].select_set(False)

    def paths(self, bm):
        """Re-derive the locked paths on a working copy of the source mesh.

        Shortened back to whatever ``begin`` trimmed: the selection on the frozen source
        still holds the edges that were cut.
        """
        selected_edges = {
            edge for edge in bm.edges if edge.select and not edge.hide
        }
        paths = selected_paths(selected_edges)
        paths, synchronized = synchronize_closed_path_phases(paths)
        paths = _apply_trims(paths, self.trims)
        if tuple(len(path[0]) for path in paths) != self.source_counts or tuple(
            bool(path[2]) for path in paths
        ) != self.closed:
            raise ValueError(pgettext("The source no longer matches the locked selection."))
        return paths, synchronized

    def capture(self, bm):
        """The count-independent half of a step, computed once per session.

        Every step plans on a fresh ``open_bmesh`` copy of the same frozen source, and
        nothing below reads the requested counts, so the whole capture is a pure function
        of that source: only element identity differs between copies.  It is therefore
        stored as indices plus copied values and re-bound onto each step's elements
        instead of recomputed.  The first call freezes and thaws too, so both routes
        hand back the same shapes and a freeze/thaw bug shows up on the first press rather
        than the second.
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
        regions, _ = capture_adjacent_strips(bm, paths)
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
        # Seams decide where the new vertices have to land: pinning the rail vertices a
        # crossing touches keeps the red line continuous across the rebuild, so the
        # crossings must be known before anything is sampled.
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
        exactly on them: the rail vertices a seam crossing runs through.

        ``shape`` is one step of the smoothing and distribution axes, or None.  A moved
        path samples from a curve refitted through its moved points: every position here
        is read off the curve object, so handing over moved coordinates without moving
        the curve changes nothing.  A path whose source cannot be fitted keeps its
        polyline fallback and only takes the moved points, and carries no measure table;
        re-weighting that fallback would mean changing a third sampler for a source that
        is already broken.

        Returns ``(coordinates, landings)``.  ``landings[path]`` says where each pinned
        source vertex was put, in the same index frame as that path's coordinate list;
        ``seams`` reads it only to report a crossing whose pin the slots could not hold.
        """
        outputs = []
        landings = []
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
                coordinates, landing = sample_by_arclength(
                    points,
                    count,
                    closed,
                    forced_anchors=path_anchors,
                )
            else:
                coordinates, landing = sample_catmull_rom_curve(
                    curve,
                    count,
                    anchors=path_anchors,
                    even=shape.t_even if shape is not None else 0.0,
                )
            outputs.append(list(coordinates))
            landings.append(landing)
        return outputs, landings

    def parameters(self, path_index, vertices, frame=None):
        """Place current path vertices in the locked source's parameter frame.

        ``frame`` replaces the polyline that projection runs against, and keeps the
        length and index space of the frozen source it stands in for.  Only a step that
        moved the path's own control points has anywhere else to project to.
        """
        return normalized_parameters(
            self.source_points[path_index] if frame is None else frame,
            self.closed[path_index],
            vertices,
            self.segments[path_index],
        )

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
        # sets ``vert.select`` and leaves every edge flag clear.  The selected vertices
        # bound exactly the edges the user meant, so read them back as edges rather than
        # refuse a selection sitting on screen.
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
                "Nothing here can be resampled.  Select a continuous chain of edges or "
                "points."
            )
        )
    # Two chains that run alongside each other but stop at different columns are the one
    # shape a band between them cannot be read from: the surface stops where the short
    # chain does, and the long chain's leftover segment has nothing opposite it.  The
    # capture says where each chain would have to stop; cut them there once and every
    # step after sees a pair it knows how to rebuild.  This is the only place the cut is
    # decided, which keeps the fitted curve, the entry counts and the frozen rung indices
    # on the same shortened rail.
    _, trims = capture_adjacent_strips(live_bm, paths)
    if trims:
        # A cut that leaves some *other* band asking for more only moved the problem, so
        # the selection goes back uncut and the capture refuses it in its own words.
        _, after = capture_adjacent_strips(
            live_bm, _apply_trims(paths, trims)
        )
        if after:
            trims = {}
    paths = _apply_trims(paths, trims)
    session = ResampleSession(obj, live_bm.copy(), paths, trims)
    _release()
    _ACTIVE = session
    _ACTIVE_KEY = obj.data.as_pointer()
    return session


def end():
    """Drop the session the scroll owned and release its source mesh.

    Unconditional on purpose: one session is live at a time, the modal that began it is
    the only caller, and ``begin`` releases whatever came before it.  The context match
    this used to do could only fail, and failing left the session and its frozen mesh
    copy standing with nothing left to free them.
    """
    clear()


def _release():
    global _ACTIVE, _ACTIVE_KEY
    if _ACTIVE is not None:
        _ACTIVE.free()
    _ACTIVE = None
    _ACTIVE_KEY = None


def clear():
    """Release the session, if any; also called when the add-on unregisters."""
    _release()
