"""Topology-aware attribute transfer helpers."""

import time

from .diagnostics import accumulate_scan
from .utils import _point

FLOAT_ATTRIBUTE_TOLERANCE = 1e-6
LONGITUDINAL_ALIGNMENT = 0.5
DISCRETE_STATE_KEYS = frozenset({"seam", "sharp"})
DEFORM_WEIGHT_TOLERANCE = 1e-6


def _float_edge_layers(bm):
    """Edge float layers such as crease and bevel weight."""
    return tuple(bm.edges.layers.float)


def _edge_state(edge, float_layers):
    """Read the BMesh edge flags without depending on Mesh datablock indices."""
    state = {
        "seam": bool(getattr(edge, "seam", False)),
        # BMesh stores the inverse of Mesh.use_edge_sharp as ``smooth``.
        "sharp": not bool(getattr(edge, "smooth", True)),
    }
    for layer in float_layers:
        value = edge[layer]
        if abs(value) > FLOAT_ATTRIBUTE_TOLERANCE:
            state[layer.name] = value
    return state


def _has_edge_state(state):
    if state["seam"] or state["sharp"]:
        return True
    return any(
        abs(value) > FLOAT_ATTRIBUTE_TOLERANCE
        for key, value in state.items()
        if key not in DISCRETE_STATE_KEYS
    )


def _apply_float_state(edge, state, layers_by_name):
    for name, value in state.items():
        if name in DISCRETE_STATE_KEYS:
            continue
        layer = layers_by_name.get(name)
        if layer is not None:
            edge[layer] = value


def _apply_edge_state(edge, state, layers_by_name):
    """Only set attributes; rebuilt edges start clean."""
    if state.get("seam"):
        edge.seam = True
    if state.get("sharp"):
        edge.smooth = False
    _apply_float_state(edge, state, layers_by_name)


def capture_path_edge_attributes(paths, bm):
    """Capture discrete flags for each source path, in path order."""
    float_layers = _float_edge_layers(bm)
    return [
        [_edge_state(edge, float_layers) for edge in path[1] if edge.is_valid]
        for path in paths
    ]


def path_projection(points, is_closed, target):
    """Locate a point on a polyline in segment-index space."""
    segment_count = len(points) if is_closed else len(points) - 1
    best = None
    for index in range(segment_count):
        start = points[index]
        end = points[(index + 1) % len(points)]
        span = end - start
        length_squared = span.length_squared
        if length_squared <= 1e-24:
            continue
        factor = max(0.0, min(1.0, (target - start).dot(span) / length_squared))
        offset_squared = (target - start.lerp(end, factor)).length_squared
        if best is None or offset_squared < best[0]:
            best = (offset_squared, index + factor, span)
    if best is None:
        return None, None
    return best[1], best[2]


def normalized_parameters(points, is_closed, vertices, segments):
    """Position of each vertex along a source path, normalized to 0..1.

    Projecting onto the source polyline puts every vertex in the same frame the
    source edges were measured in, independently of how many segments the
    current step uses or how evenly they are spaced.
    """
    if segments <= 0.0:
        return [0.0] * len(vertices)
    started = time.perf_counter()
    segment_count = len(points) if is_closed else len(points) - 1
    parameters = []
    for vertex in vertices:
        parameter, _ = path_projection(points, is_closed, _point(vertex))
        parameters.append(0.0 if parameter is None else parameter / segments)
    accumulate_scan(
        "path-projection", time.perf_counter() - started, len(vertices) * segment_count
    )
    return parameters


def _u_distance(first, second, closed):
    difference = abs(first - second)
    return min(difference, 1.0 - difference) if closed else difference


def merge_edge_states(weighted):
    """Combine source states that collapsed onto one target edge.

    ``(weight, state)`` pairs are weighted by how much of the target each
    source covers.  Discrete flags resolve by weighted majority with ties
    favouring preservation, because losing a seam silently is worse than
    keeping one extra.  Float layers average, and a layer absent from a state
    counts as zero over that state's whole weight.
    """
    total = sum(weight for weight, _ in weighted)
    if total <= 0.0:
        return dict(weighted[0][1])
    merged = {}
    for key in DISCRETE_STATE_KEYS:
        keep = sum(weight for weight, state in weighted if state.get(key))
        merged[key] = keep * 2.0 >= total
    float_keys = {
        key
        for _, state in weighted
        for key in state
        if key not in DISCRETE_STATE_KEYS
    }
    for key in float_keys:
        average = sum(
            weight * state.get(key, 0.0) for weight, state in weighted
        ) / total
        if abs(average) > FLOAT_ATTRIBUTE_TOLERANCE:
            merged[key] = average
    return merged


def _edge_spans(parameters, closed):
    """Span of every path edge in the normalized frame, split at a wrap."""
    count = len(parameters)
    spans = []
    for index in range(count if closed else count - 1):
        start = parameters[index]
        end = parameters[(index + 1) % count] if closed else parameters[index + 1]
        if closed and end < start:
            spans.append(((start, 1.0), (0.0, end)))
        else:
            spans.append(((min(start, end), max(start, end)),))
    return spans


def resample_edge_states(parameters, states, closed):
    """Resample frozen source edge states onto a new edge count.

    Source edge ``i`` of ``M`` owns ``[i/M, (i+1)/M]`` for both open and closed
    paths, since an open path's last vertex sits at u=1.  Each new edge takes a
    weighted merge of every source edge it overlaps, so shrinking blends rather
    than discards and growing back out lands on the same values.
    """
    source_count = len(states)
    if source_count == 0 or len(parameters) < 2:
        return []
    resampled = []
    for index, span in enumerate(_edge_spans(parameters, closed)):
        weighted = []
        for source_index, state in enumerate(states):
            start = source_index / source_count
            end = (source_index + 1) / source_count
            overlap = sum(
                min(piece_end, end) - max(piece_start, start)
                for piece_start, piece_end in span
            )
            if overlap > 0.0:
                weighted.append((overlap, state))
        if not weighted:
            # A zero-length span means two vertices share a position; keep the
            # count aligned by taking the source edge under the span start.
            weighted = [
                (
                    1.0,
                    states[min(int(parameters[index] * source_count), source_count - 1)],
                )
            ]
        resampled.append(merge_edge_states(weighted))
    return resampled


def _destroyed_region_edges(region):
    """Region edges whose every face is deleted, so the edge itself disappears."""
    faces = set(region.get("faces", ()))
    return [
        edge
        for edge in region.get("delete_edges", ())
        if edge.is_valid and all(face in faces for face in edge.link_faces)
    ]


def capture_region_edge_attributes(regions, paths, bm):
    """Record attributes of region edges that resampling destroys.

    Each record stores where the edge sat along the region's inner boundary as a
    normalized parameter, so it stays meaningful no matter how many segments a
    later step uses.  Edges parallel to the path are skipped: they run along the
    ladder and have no counterpart rung.  Seam edges are recorded like any other;
    :func:`apply_region_edge_attributes` is what decides whether one travels by
    position or is already carried by the rung a crossing became.
    """
    float_layers = _float_edge_layers(bm)
    captured = []
    for region in regions:
        frames = region["frames"]
        is_closed = frames["closed"]
        points = frames["inner"]["points"]
        segments = frames["inner"]["segments"]
        path_vertices = paths[region["path_index"]][0]
        path_index_by_vertex = {
            vertex: index for index, vertex in enumerate(path_vertices)
        }
        records = []
        started = time.perf_counter()
        projection_scans = 0
        for edge in _destroyed_region_edges(region):
            state = _edge_state(edge, float_layers)
            if not _has_edge_state(state):
                continue
            first, second = edge.verts
            first_index = path_index_by_vertex.get(first)
            second_index = path_index_by_vertex.get(second)
            if first_index is not None and second_index is not None:
                # Path edges are restored by apply_path_edge_attributes.
                continue
            inner_index = None
            if first_index is not None or second_index is not None:
                # Anchoring on the shared path vertex keeps a seam that crosses
                # the path continuous across both neighbouring regions.
                inner_index = first_index if first_index is not None else second_index
                parameter = float(inner_index)
            else:
                midpoint = (first.co + second.co) * 0.5
                parameter, tangent = path_projection(points, is_closed, midpoint)
                projection_scans += len(points)
                if parameter is None:
                    continue
                direction = second.co - first.co
                if direction.length <= 1e-12:
                    continue
                if (
                    abs(direction.normalized().dot(tangent.normalized()))
                    > LONGITUDINAL_ALIGNMENT
                ):
                    continue
            records.append(
                {
                    "u": parameter / segments,
                    "inner_index": inner_index,
                    "state": state,
                }
            )
        accumulate_scan(
            "edge-capture-projection", time.perf_counter() - started, projection_scans
        )
        captured.append({"closed": is_closed, "records": records})
    return captured


def apply_region_edge_attributes(bm, region, inner_parameters, rungs, pinned=()):
    """Restore the attributes of the cross-band edges the rebuild destroyed.

    ``rungs`` lists the rebuilt ones as ``(inner index, edge endpoints)`` in ladder
    order, so a record lands on the nearest one and the edge itself is looked up by
    its two endpoints instead of being rediscovered from the rebuilt faces.
    ``pinned`` holds the source inner index of every seam crossing that became a
    rung; that column already carries the red line, so the record it was made from is
    dropped here rather than drawn a second time beside it.  A crossing that could
    not become a rung is absent from ``pinned`` and is restored by position like any
    other edge.
    """
    captured = region.get("edge_attributes") or {}
    records = [
        record
        for record in (captured.get("records") or ())
        if not (record["state"].get("seam") and record.get("inner_index") in pinned)
    ]
    if not records or not rungs:
        return
    closed = bool(captured.get("closed"))

    # Records outnumber rungs whenever the count drops, so gather every record
    # per rung and merge; last-write-wins silently dropped the others.
    grouped = {}
    started = time.perf_counter()
    compared = 0
    for record in records:
        best = None
        for position, (inner_index, _) in enumerate(rungs):
            compared += 1
            distance = _u_distance(
                inner_parameters[inner_index], record["u"], closed
            )
            if best is None or distance < best[0]:
                best = (distance, position)
        if best is None:
            continue
        grouped.setdefault(best[1], []).append((1.0, record["state"]))
    accumulate_scan("rung-match", time.perf_counter() - started, compared)

    layers_by_name = {layer.name: layer for layer in _float_edge_layers(bm)}
    for position, weighted in grouped.items():
        edge = bm.edges.get(rungs[position][1])
        if edge is not None:
            _apply_edge_state(edge, merge_edge_states(weighted), layers_by_name)


def region_outer_parameters(region, outer_vertices, frame_points=None):
    """Place the outer rail in the frozen frame its seam crossings were measured in.

    A fixed rail projects back onto itself exactly; a rail that is itself a
    resampled path only approximates it, which is enough to pick the nearest
    vertex for a crossing to land on.

    ``frame_points`` stands in for that rail's own frozen points where the step moved
    them, which keeps the approximation the same size it always was: a moved rail
    sampled from its own moved curve is only off the frame it is asked about by the
    difference between that curve and its chords.
    """
    frames = region.get("frames") or {}
    outer = frames.get("outer") or {}
    points = frame_points or outer.get("points") or ()
    if not points or not outer_vertices:
        return []
    return normalized_parameters(
        points,
        bool(frames.get("closed")),
        outer_vertices,
        outer.get("segments") or 1,
    )


def apply_path_edge_attributes(
    updated_paths,
    path_parameters,
    source_states,
    bm,
):
    """Apply frozen source edge attributes to newly rebuilt path edges."""
    layers_by_name = {layer.name: layer for layer in _float_edge_layers(bm)}
    for path_index, updated_path in enumerate(updated_paths):
        if path_index >= len(source_states) or path_index >= len(path_parameters):
            continue
        states = source_states[path_index]
        parameters = path_parameters[path_index]
        vertices, edges = updated_path[0], updated_path[1]
        if not states or len(parameters) != len(vertices):
            continue
        resampled = resample_edge_states(parameters, states, bool(updated_path[2]))
        for edge, state in zip(edges, resampled):
            if not edge.is_valid:
                continue
            edge.seam = bool(state.get("seam"))
            edge.smooth = not bool(state.get("sharp"))
            _apply_float_state(edge, state, layers_by_name)


def _blend_weights(left, right, factor):
    if factor <= 0.0:
        return dict(left)
    if factor >= 1.0:
        return dict(right)
    merged = {}
    for group_index in set(left) | set(right):
        first = left.get(group_index, 0.0)
        second = right.get(group_index, 0.0)
        value = first + (second - first) * factor
        if value > DEFORM_WEIGHT_TOLERANCE:
            merged[group_index] = value
    return merged


def _blend_values(left, right, factor):
    if factor <= 0.0:
        return left.copy()
    if factor >= 1.0:
        return right.copy()
    return left.lerp(right, factor)


def _point_positions(parameters, source_count, closed):
    """Where each rebuilt vertex falls between two source vertices, as (left, right, factor).

    Source vertex ``i`` sits at ``i / segments`` in the same frozen frame the
    path parameters use.  Landing exactly on one reports factor 0 or 1, and the
    blend helpers then copy it untouched -- that is what keeps a count stepped
    down and back up bit-for-bit.
    """
    if source_count == 0:
        return []
    if source_count == 1:
        return [(0, 0, 0.0) for _ in parameters]
    segments = source_count if closed else source_count - 1
    positions = []
    for parameter in parameters:
        position = parameter * segments
        if closed:
            whole = int(position)
            index = whole % source_count
            following = (index + 1) % source_count
            factor = position - whole
        else:
            position = max(0.0, min(position, segments))
            index = min(int(position), segments - 1)
            following = index + 1
            factor = position - index
        positions.append((index, following, factor))
    return positions


def _point_value_layers(bm):
    """Vertex-domain layers carried along a path, as ``(kind, name, layer)``.

    Only layers already on the mesh are listed: ``deform.active`` reads the
    vertex-group layer without creating one, and iterating a layer collection
    never adds either, so a mesh with neither vertex groups nor point colors
    yields nothing and every later step stays a no-op.
    """
    layers = []
    deform = bm.verts.layers.deform.active
    if deform is not None:
        layers.append(("weight", deform.name, deform))
    for kind, collection in (
        ("color", bm.verts.layers.color),
        ("float_color", bm.verts.layers.float_color),
    ):
        for layer in collection:
            layers.append((kind, layer.name, layer))
    return layers


def capture_path_point_attributes(paths, bm):
    """Freeze each source path vertex's weights and point colors, or None.

    Colors stored per vertex rather than per corner cannot ride the rail chains
    in :mod:`.surface`, so they travel with the weights here instead.
    """
    layers = _point_value_layers(bm)
    if not layers:
        return None
    captured = []
    for kind, name, layer in layers:
        per_path = []
        for vertices, _, closed in paths:
            if kind == "weight":
                values = [dict(vertex[layer]) for vertex in vertices]
            else:
                values = [vertex[layer].copy() for vertex in vertices]
            per_path.append((values, bool(closed)))
        captured.append((kind, name, per_path))
    return captured


def apply_path_point_attributes(updated_paths, path_parameters, captured, bm):
    """Restore resampled weights and point colors onto the rebuilt path vertices.

    Only path vertices are rewritten: a static outer rail keeps its vertices and
    therefore their values, and a resampled outer rail is itself a path handled
    here.
    """
    if not captured:
        return
    layers = {name: layer for _, name, layer in _point_value_layers(bm)}
    for kind, name, per_path in captured:
        layer = layers.get(name)
        if layer is None:
            continue
        for path_index, (values, closed) in enumerate(per_path):
            if path_index >= len(updated_paths) or path_index >= len(path_parameters):
                continue
            vertices = updated_paths[path_index][0]
            parameters = path_parameters[path_index]
            if not values or len(parameters) != len(vertices):
                continue
            positions = _point_positions(parameters, len(values), closed)
            for (left, right, factor), vertex in zip(positions, vertices):
                if kind == "weight":
                    merged = _blend_weights(values[left], values[right], factor)
                    stored = vertex[layer]
                    stored.clear()
                    for group_index, weight in merged.items():
                        stored[group_index] = weight
                else:
                    vertex[layer] = _blend_values(values[left], values[right], factor)
