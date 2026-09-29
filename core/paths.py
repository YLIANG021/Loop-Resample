"""Selected-edge path ordering and component discovery."""

from collections import deque

from ..i18n import pgettext


def _closed_loop_anchor(loop_vertices):
    """Closed-loop start: a vertex a seam runs through, else the lowest index.

    The start vertex is the one resampling pins in place and the phase every
    other sample is measured from, so anchoring it on a seam keeps that seam
    under a rebuilt vertex instead of letting it drift to the nearest rung.
    Deterministic -- reads only frozen source flags and vertex indices -- so each
    step re-derives the same anchor and stays aligned with the samples frozen at
    session start.  A single loop honors this directly; when several loops
    synchronize, synchronize_closed_path_phases re-anchors the root by lowest
    index and the rest by mapping, so this only shifts loops that never sync.
    """
    seam_vertices = [
        vertex
        for vertex in loop_vertices
        if any(edge.seam for edge in vertex.link_edges)
    ]
    return min(seam_vertices or list(loop_vertices), key=lambda vertex: vertex.index)


def ordered_selected_path(edges):
    """Return (vertices, edges, is_closed) for one non-branching component."""
    if not edges:
        raise ValueError(pgettext("Select a continuous chain of edges or points."))

    adjacency = {}
    for edge in edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)

    degrees = {vertex: len(vertex_edges) for vertex, vertex_edges in adjacency.items()}
    endpoints = [vertex for vertex, degree in degrees.items() if degree == 1]
    branching = [vertex for vertex, degree in degrees.items() if degree > 2]
    if branching:
        raise ValueError(
            pgettext(
                "The selected edges cross each other.  Keep only one direction of them."
            )
        )

    is_closed = not endpoints
    if is_closed:
        start = _closed_loop_anchor(adjacency)
    elif len(endpoints) == 2:
        start = min(endpoints, key=lambda vertex: vertex.index)
    else:
        raise ValueError(
            pgettext(
                "The selected edges are not joined, so they cannot form one continuous "
                "chain."
            )
        )

    ordered_vertices = []
    ordered_edges = []
    used_edges = set()
    current = start

    def leave(vertex, used):
        candidates = [edge for edge in adjacency[vertex] if edge not in used]
        if not candidates:
            return None
        # A closed loop has two ways out of its start vertex and set iteration
        # order follows element ids, so pick by index to stay reproducible.
        return min(
            candidates,
            key=lambda edge: min(other.index for other in edge.verts if other != vertex),
        )

    while True:
        ordered_vertices.append(current)
        next_edge = leave(current, used_edges)
        if next_edge is None:
            break

        used_edges.add(next_edge)
        ordered_edges.append(next_edge)
        current = next(vertex for vertex in next_edge.verts if vertex != current)

        if is_closed and current == start:
            break

    if len(used_edges) != len(edges):
        raise ValueError(
            pgettext(
                "The selected edges are not continuous; there is a gap in between."
            )
        )
    if not is_closed and current not in endpoints:
        raise ValueError(
            pgettext(
                "The selected edges close back into a ring.  Break the loop and try again."
            )
        )

    return ordered_vertices, ordered_edges, is_closed


def edge_components(edges):
    """Split selected edges into vertex-connected components."""
    remaining = set(edges)
    components = []
    while remaining:
        seed = remaining.pop()
        component = {seed}
        stack = [seed]
        while stack:
            edge = stack.pop()
            neighbors = {
                linked
                for vertex in edge.verts
                for linked in vertex.link_edges
                if linked in remaining
            }
            remaining.difference_update(neighbors)
            component.update(neighbors)
            stack.extend(neighbors)
        components.append(component)
    return components


def selected_paths(selected_edges):
    paths = [ordered_selected_path(component) for component in edge_components(selected_edges)]
    paths.sort(key=lambda path: min(vertex.index for vertex in path[0]))
    return paths


def _closed_path_reorder(path, anchor, forward):
    vertices, edges, _ = path
    anchor_index = vertices.index(anchor)
    count = len(vertices)
    ordered_vertices = tuple(
        vertices[(anchor_index + (offset if forward else -offset)) % count]
        for offset in range(count)
    )
    edge_lookup = {
        frozenset(edge.verts): edge
        for edge in edges
    }
    ordered_edges = tuple(
        edge_lookup[frozenset((ordered_vertices[index], ordered_vertices[(index + 1) % count]))]
        for index in range(count)
    )
    return ordered_vertices, ordered_edges, True


def synchronize_closed_path_phases(paths):
    """Synchronize closed loops when selected quad faces give a full mapping."""
    closed_indices = {
        index for index, path in enumerate(paths) if path[2]
    }
    if len(closed_indices) < 2:
        return list(paths), set()

    vertex_to_path = {
        vertex: index
        for index in closed_indices
        for vertex in paths[index][0]
    }
    pair_maps = {}
    invalid_pairs = set()
    for face in {
        linked_face
        for index in closed_indices
        for vertex in paths[index][0]
        for linked_face in vertex.link_faces
    }:
        path_ids = {
            vertex_to_path.get(vertex)
            for vertex in face.verts
        }
        path_ids.discard(None)
        if len(path_ids) != 2 or len(face.verts) != 4:
            continue
        first, second = sorted(path_ids)
        first_vertices = [vertex for vertex in face.verts if vertex_to_path.get(vertex) == first]
        second_vertices = [vertex for vertex in face.verts if vertex_to_path.get(vertex) == second]
        if len(first_vertices) != 2 or len(second_vertices) != 2:
            continue
        for edge in face.edges:
            left, right = edge.verts
            left_path = vertex_to_path.get(left)
            right_path = vertex_to_path.get(right)
            if {left_path, right_path} != {first, second}:
                continue
            if left_path == first:
                source, target = left, right
            else:
                source, target = right, left
            mapping = pair_maps.setdefault((first, second), {})
            reverse = pair_maps.setdefault((second, first), {})
            if mapping.get(source, target) is not target or reverse.get(target, source) is not source:
                invalid_pairs.add((first, second))
                invalid_pairs.add((second, first))
                continue
            mapping[source] = target
            reverse[target] = source

    adjacency = {index: set() for index in closed_indices}
    for (first, second), mapping in pair_maps.items():
        if (first, second) in invalid_pairs:
            continue
        if len(mapping) == len(paths[first][0]) == len(paths[second][0]):
            adjacency[first].add(second)

    reordered = list(paths)
    synchronized = set()
    for root in sorted(
        closed_indices,
        key=lambda index: min(vertex.index for vertex in reordered[index][0]),
    ):
        if root in synchronized or not adjacency[root]:
            continue
        root_anchor = min(reordered[root][0], key=lambda vertex: vertex.index)
        reordered[root] = _closed_path_reorder(reordered[root], root_anchor, True)
        synchronized.add(root)
        pending = deque((root,))
        while pending:
            current = pending.popleft()
            current_vertices = reordered[current][0]
            for neighbor in sorted(adjacency[current]):
                if neighbor in synchronized:
                    continue
                mapping = pair_maps[(current, neighbor)]
                anchor = mapping.get(current_vertices[0])
                following = mapping.get(current_vertices[1])
                if anchor is None or following is None:
                    continue
                neighbor_vertices = reordered[neighbor][0]
                anchor_index = neighbor_vertices.index(anchor)
                forward = neighbor_vertices[(anchor_index + 1) % len(neighbor_vertices)] is following
                reordered[neighbor] = _closed_path_reorder(
                    reordered[neighbor],
                    anchor,
                    forward,
                )
                synchronized.add(neighbor)
                pending.append(neighbor)
    return reordered, synchronized
