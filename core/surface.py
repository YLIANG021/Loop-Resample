"""Per-source-face shading and loop UV transfer.

A rebuilt face is matched to the source face that occupied the same place along
the region, then inherits that face's material and shading.  UVs travel on per-
rail chains: one rail's source corners sorted by u, where corners disagreeing at
the same u start a new chain.  A chain is therefore one island's continuous
polyline along the rail, and sampling the chain of the matched source face keeps
neighbouring rebuilt faces in agreement at every shared vertex while an island
boundary still cuts them apart.  Note this splits on the *stored values*, which is
not the same set of edges as the marked seam -- the seam drives where new vertices
land (see :mod:`.seams`), while this only decides which island a corner reads
from.  Corner vertex colors -- both the byte and the float layer Blender
exposes -- travel the same chains and share the split-when-corners-disagree rule,
so a color change is preserved even where it coincides with a UV seam; only UV
layers are treated as periodic.

Only two v values ever occur -- 0 on the inner rail, 1 on the outer rail -- so
sampling a face reduces to interpolating along the rail the corner belongs to.
"""

import time

from mathutils import Vector

from .attributes import _u_distance
from .diagnostics import (
    accumulate_scan,
    print_uv_faces,
    print_uv_note,
    print_uv_region,
)
from .regions import region_rails

_UV_MERGE_DECIMALS = 6

# Stays True while the add-on is being tuned; the [uvdiag] block it gates is removed
# in one go at the end.  Set False to silence those lines without touching geometry.
DIAGNOSE_UV = True


def _corner_layers(bm):
    """Every per-corner value this pipeline carries, keyed by ``(kind, name)``.

    A corner color is a 4-component Vector in BMesh and is assigned directly to
    the layer, unlike a UV, which is a struct with a ``.uv`` field.
    """
    layers = {}
    for layer in bm.loops.layers.uv:
        layers[("uv", layer.name)] = ("uv", layer)
    for kind, collection in (
        ("color", bm.loops.layers.color),
        ("float_color", bm.loops.layers.float_color),
    ):
        for layer in collection:
            layers[(kind, layer.name)] = (kind, layer)
    return layers


def capture_region_faces(bm, region, paths):
    """Record every source face as shading plus the region's two rail chains.

    A face with no corner on the inner rail -- an outer row of a region deeper
    than one quad -- is left out: the rebuild collapses such rows into a single
    ladder, so only the inner row has a counterpart to hand its corners to.
    """
    frames = region["frames"]
    closed = frames["closed"]
    inner_segments = frames["inner"]["segments"]
    outer_segments = frames["outer"]["segments"]
    inner_vertices, outer_vertices = region_rails(region, paths)
    inner_index = {vertex: index for index, vertex in enumerate(inner_vertices)}
    outer_index = {vertex: index for index, vertex in enumerate(outer_vertices)}
    value_layers = _corner_layers(bm)

    builders = (_RailBuilder(closed), _RailBuilder(closed))
    records = []
    bounds = {
        key: [1.0e30, -1.0e30]
        for key, (kind, _) in value_layers.items()
        if kind == "uv"
    }
    for face in region["faces"]:
        if not face.is_valid:
            continue
        corners = []
        for loop in face.loops:
            vertex = loop.vert
            if vertex in inner_index:
                rail, u = 0, inner_index[vertex] / inner_segments
            elif vertex in outer_index:
                rail, u = 1, outer_index[vertex] / outer_segments
            else:
                # A fan pole sits on neither rail; its u becomes the centre of
                # the face's inner corners, resolved once they are all known.
                rail, u = 1, None
            values = {}
            for key, (kind, layer) in value_layers.items():
                if kind == "uv":
                    values[key] = loop[layer].uv.copy()
                else:
                    values[key] = loop[layer].copy()
            corners.append(
                {"vertex": vertex, "rail": rail, "u": u, "values": values}
            )
        inner_us = [
            corner["u"]
            for corner in corners
            if corner["rail"] == 0 and corner["u"] is not None
        ]
        if not inner_us:
            continue
        start, end = _u_span(inner_us, closed)
        center = _u_center(start, end, closed)
        for corner in corners:
            if corner["u"] is None:
                corner["u"] = center
            for key, value in corner["values"].items():
                if key not in bounds:
                    continue
                low, high = bounds[key]
                bounds[key] = [
                    min(low, value.x, value.y),
                    max(high, value.x, value.y),
                ]
        chains = {}
        for rail in (0, 1):
            by_vertex = {
                corner["vertex"]: corner for corner in corners if corner["rail"] == rail
            }
            pairs = [
                (by_vertex[edge.verts[0]], by_vertex[edge.verts[1]])
                for edge in face.edges
                if edge.verts[0] in by_vertex and edge.verts[1] in by_vertex
            ]
            chains[rail] = builders[rail].add(list(by_vertex.values()), pairs)
        records.append(
            {
                "material_index": int(face.material_index),
                "smooth": bool(face.smooth),
                "u_start": start,
                "u_end": end,
                "u_center": center,
                "chains": chains,
            }
        )

    rails = []
    indices = []
    for builder in builders:
        chain_list, index = builder.chains()
        rails.append(chain_list)
        indices.append(index)
    for record in records:
        chains = {}
        for rail, token in record["chains"].items():
            chains[rail] = (
                None
                if token is None
                else indices[rail][builders[rail]._find(token)]
            )
        record["chains"] = chains
    return {
        "closed": closed,
        "records": records,
        "rails": rails,
        "periodic": _periodic_layers(bounds, closed),
    }


class _RailBuilder:
    """One rail's source corners, merged into continuous per-island chains.

    Corners sharing a u and a UV value become one knot; every source face edge
    along the rail stitches two knots together.  A corner whose UV disagrees with
    its neighbour's therefore splits into two knots that nothing stitches, which is
    what keeps islands apart.
    """

    def __init__(self, closed):
        self._closed = closed
        self._parent = {}
        self._values = {}
        self._wrap_edges = []

    def add(self, corners, pairs):
        """Register one face's rail corners; return a token for its chain."""
        if not corners:
            return None
        for corner in corners:
            self._node(self._key(corner), corner["values"])
        for first, second in pairs:
            a = self._find(self._key(first))
            b = self._find(self._key(second))
            # Checked before the same-component skip: on a closed rail the face
            # crossing u=1 arrives last, when both knots are already stitched.
            if self._closed and abs(first["u"] - second["u"]) > 0.5:
                self._wrap_edges.append((a, b))
            if a == b:
                continue
            self._parent[b] = a
        # A token, not a root: later faces may re-root this component, so the
        # record keeps a node key and resolves it once every face is in.
        if pairs:
            return self._key(pairs[0][0])
        return self._key(corners[0])

    def chains(self):
        groups = {}
        for key in self._parent:
            groups.setdefault(self._find(key), []).append(key)
        wrapped = {self._find(a) for a, _ in self._wrap_edges}
        chains = []
        index = {}
        for root, keys in groups.items():
            keys.sort(key=lambda key: key[0])
            index[root] = len(chains)
            chains.append(
                {
                    "closed": root in wrapped,
                    "knots": [(key[0], self._values[key]) for key in keys],
                }
            )
        return chains, index

    def _key(self, corner):
        return (
            corner["u"],
            tuple(
                (
                    key,
                    tuple(round(component, _UV_MERGE_DECIMALS) for component in value),
                )
                for key, value in sorted(corner["values"].items())
            ),
        )

    def _node(self, key, uv):
        if key not in self._parent:
            self._parent[key] = key
            self._values[key] = uv
        return self._find(key)

    def _find(self, key):
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root


def _periodic_layers(bounds, closed):
    """Layers that fit inside one texture tile, so a wrap means exactly +/-1.

    A layer spread over several tiles is an atlas offset; its period is unknown,
    and guessing there would shift corners by a whole tile.
    """
    if not closed:
        return frozenset()
    return frozenset(
        name
        for name, (low, high) in bounds.items()
        if low >= -1e-4 and high <= 1.0 + 1e-4
    )


def apply_region_faces(
    bm,
    rebuilt_faces,
    region,
    inner_vertices,
    inner_parameters,
    outer_vertices=(),
    outer_parameters=(),
):
    """Give every rebuilt face the shading and corner values of its source face."""
    captured = region.get("source_faces") or {}
    records = captured.get("records")
    if not records:
        if DIAGNOSE_UV:
            print_uv_note(
                region,
                f"no-source-records source_faces={len(region.get('faces') or ())}",
            )
        # Rebuild already stamped the region defaults, and there is nothing to
        # interpolate from.
        return
    closed = bool(captured.get("closed"))
    layers_by_key = _corner_layers(bm)
    periodic = captured.get("periodic", frozenset())
    rails = captured.get("rails") or ([], [])
    inner_index = {vertex: index for index, vertex in enumerate(inner_vertices)}
    outer_index = {vertex: index for index, vertex in enumerate(outer_vertices)}
    if DIAGNOSE_UV:
        print_uv_region(
            region, rails, region.get("seam_crossings") or (),
            (inner_parameters, outer_parameters),
        )
    uv_layer = bm.loops.layers.uv.active if DIAGNOSE_UV else None
    rows = []

    for face in rebuilt_faces:
        if not face.is_valid:
            continue
        corners = []
        inner_us = []
        outer_us = []
        for loop in face.loops:
            vertex = loop.vert
            index = inner_index.get(vertex)
            if index is not None:
                u = inner_parameters[index]
                corners.append((loop, 0, u, index))
                inner_us.append(u)
                continue
            index = outer_index.get(vertex)
            if index is not None:
                u = outer_parameters[index]
                outer_us.append(u)
            else:
                u = None
            corners.append((loop, 1, u, index))
        start, end = _u_span(inner_us, closed)
        center = _u_center(start, end, closed=closed)
        corner_us = (inner_us, outer_us)
        vote = {} if DIAGNOSE_UV else None
        record = _match_face(records, start, end, closed, vote)
        off_island = not _island_reaches(record, corner_us, rails)
        if off_island:
            record = (
                _match_island(records, start, end, closed, corner_us, rails)
                or record
            )
        face.material_index = record["material_index"]
        face.smooth = record["smooth"]
        outer_span = _u_span(outer_us, closed) if DIAGNOSE_UV else None
        chains = record["chains"]
        probes = [] if DIAGNOSE_UV else None
        for loop, rail, u, corner_index in corners:
            chain_index = chains.get(rail)
            if chain_index is None:
                continue
            sample = _sample_chain(
                rails[rail][chain_index],
                center if u is None else u,
                periodic,
                probes,
            )
            if DIAGNOSE_UV:
                probes[-1]["rail"] = rail
                probes[-1]["chain"] = chain_index
                probes[-1]["vertex_index"] = corner_index
            for key, value in sample.items():
                entry = layers_by_key.get(key)
                if entry is None:
                    continue
                kind, layer = entry
                if kind == "uv":
                    loop[layer].uv = value
                else:
                    loop[layer] = value
        if DIAGNOSE_UV:
            rows.append(
                {
                    "face_index": face.index,
                    "vertices": ",".join(
                        str(vertex.index) for vertex in face.verts
                    ),
                    "center": face.calc_center_median(),
                    "corner_rails": " ".join(
                        f"r{rail}v{index}"
                        + ("" if u is None else f"@{u:.6f}")
                        for _, rail, u, index in corners
                    ),
                    "inner_corners": len(inner_us),
                    "outer_corners": len(corners) - len(inner_us),
                    "inner_start": start,
                    "inner_end": end,
                    "outer_start": outer_span[0],
                    "outer_end": outer_span[1],
                    "record_start": record["u_start"],
                    "record_end": record["u_end"],
                    "record_center": record["u_center"],
                    "overlap": vote["overlap"],
                    "tied": vote["tied"],
                    "fallback": vote["fallback"],
                    "near_seam": _crosses_seam(
                        start,
                        end,
                        region.get("seam_crossings") or (),
                        closed,
                    ),
                    "material": record["material_index"],
                    "island_vote": off_island,
                    "probes": probes,
                    "uvs": ""
                    if uv_layer is None
                    else " ".join(
                        "({:.4f},{:.4f})".format(
                            loop[uv_layer].uv.x, loop[uv_layer].uv.y
                        )
                        for loop in face.loops
                    ),
                }
            )
    if DIAGNOSE_UV:
        print_uv_faces(region, rows, len(rebuilt_faces))


def _crosses_seam(start, end, crossings, closed):
    """Whether any captured seam crossing falls inside a face's matched footprint.

    A crossing sits on a column boundary, so this flags the faces on both sides of
    it -- the neighborhood where a wrong island can be sampled from.
    """
    return any(
        _arc_contains(start, end, crossing["inner_u"], closed)
        or _arc_contains(start, end, crossing["outer_u"], closed)
        for crossing in crossings
    )


def _arc_contains(start, end, value, closed):
    return any(
        low - 1e-9 <= value <= high + 1e-9
        for low, high in _arc_pieces(start, end, closed)
    )


def _island_reaches(record, corner_us, rails):
    """Whether one source face's island can supply every corner a rebuilt face has.

    A rebuilt face sits inside a single island, and a source face names that island
    with one chain per rail -- the pair of them, never either one on its own.  When
    either chain cannot reach the corners this face has on its rail, the face is not in
    that island, and taking it anyway clamps a corner onto a knot that is not its own:
    both rails losing the same way collapses the face to a line along the seam, and
    only one of them losing stretches a wire across the UV map to the other island.
    """
    chains = record["chains"]
    for rail, us in enumerate(corner_us):
        chain_index = chains.get(rail)
        if chain_index is None or not us:
            continue
        chain = rails[rail][chain_index]
        if not all(_chain_reaches(chain, u) for u in us):
            return False
    return True


def _match_island(records, start, end, closed, corner_us, rails):
    """The source face on the island a rebuilt face actually sits in.

    Only consulted once the overlap vote has been rejected.  A triangle step has a
    single inner corner, so its inner span is a point that overlaps nothing and the
    vote falls back to the nearest centre -- which can land across the seam and hand
    back the neighbouring island's corner set.  Overlap still ranks the candidates, so
    a face that does cover a source face keeps following that one.
    """
    span = _arc_pieces(start, end, closed)
    center = _u_center(start, end, closed)
    best = None
    best_key = None
    for record in records:
        if not _island_reaches(record, corner_us, rails):
            continue
        overlap = _arc_overlap(
            span, _arc_pieces(record["u_start"], record["u_end"], closed)
        )
        key = (-overlap, _u_distance(record["u_center"], center, closed))
        if best is None or key < best_key:
            best, best_key = record, key
    return best


def _chain_reaches(chain, u):
    """Whether sampling ``chain`` at u reads between its knots instead of clamping."""
    knots = chain["knots"]
    low, high = knots[0][0], knots[-1][0]
    if len(knots) == 1:
        return abs(u - low) <= 1e-9
    if chain["closed"]:
        # The chain wraps through 0/1: its arc runs from its first knot to that knot
        # plus one, and a u below the start is read one turn later, as _sample_chain
        # does it.  Judging it against the last knot instead would call it reachable
        # in the wrong direction.
        high = low + 1.0
        if u < low:
            u += 1.0
    return low - 1e-9 <= u <= high + 1e-9


def _match_face(records, start, end, closed, probe=None):
    """The source face the rebuilt face mostly covers along the region.

    Once counts change, a rebuilt face can straddle a material or shading
    boundary, and a centre-only vote flips the whole face to whichever side the
    centre happens to land on; the overlap majority follows the source face the
    new face actually covers most of.  A span degenerate on the inner rail -- the
    face a triangle step turned into a single inner corner -- overlaps nothing and
    falls back to the nearest centre.

    ``probe`` is the temporary diagnostic's dict: it learns whether the vote was
    won outright and, if it was not, how many source faces tied for it.
    """
    started = time.perf_counter()
    span = _arc_pieces(start, end, closed)
    best = None
    best_overlap = 0.0
    tied = 0
    for record in records:
        overlap = _arc_overlap(
            span, _arc_pieces(record["u_start"], record["u_end"], closed)
        )
        if overlap > best_overlap:
            best, best_overlap, tied = record, overlap, 1
        elif probe is not None and overlap > 0.0:
            tied += 1
    work = len(records)
    fallback = best is None
    if fallback:
        center = _u_center(start, end, closed)
        best = min(
            records,
            key=lambda record: _u_distance(record["u_center"], center, closed),
        )
        work += len(records)
    if probe is not None:
        probe["overlap"] = best_overlap
        probe["tied"] = tied
        probe["fallback"] = fallback
    accumulate_scan("face-match", time.perf_counter() - started, work)
    return best


def _arc_pieces(start, end, closed):
    """One u arc as at most two non-wrapping (low, high) pieces."""
    if not closed or end >= start:
        return [(start, end)]
    return [(start, 1.0), (0.0, end)]


def _arc_overlap(first, second):
    return sum(
        max(0.0, min(high_a, high_b) - max(low_a, low_b))
        for low_a, high_a in first
        for low_b, high_b in second
    )


def _sample_chain(chain, u, periodic, probe=None):
    """Interpolate one island's rail polyline at u, as {layer name: Vector}.

    ``probe`` is the temporary diagnostic's list: one entry per sample recording
    the u asked for, the u window the chain actually covers, and whether the
    answer had to be clamped to an end knot.
    """
    knots = chain["knots"]
    if len(knots) == 1:
        if probe is not None:
            probe.append(
                {
                    "u": u,
                    "low": knots[0][0],
                    "high": knots[0][0],
                    "clamped": abs(u - knots[0][0]) > 1e-9,
                }
            )
        return knots[0][1]
    points = knots
    # A chain that runs all the way around a closed rail continues from its last
    # knot into its first across u=1.
    if chain["closed"]:
        points = knots + [(knots[0][0] + 1.0, knots[0][1])]
        if u < points[0][0]:
            u += 1.0
    index = 0
    while index < len(points) - 2 and u > points[index + 1][0]:
        index += 1
    accumulate_scan("chain-sample", 0.0, index + 1)
    first_u, first_uv = points[index]
    second_u, second_uv = points[index + 1]
    span = second_u - first_u
    factor = 0.0 if span <= 1e-12 else (u - first_u) / span
    if probe is not None:
        probe.append(
            {
                "u": u,
                "low": points[0][0],
                "high": points[-1][0],
                "clamped": factor < 0.0 or factor > 1.0,
            }
        )
    factor = max(0.0, min(1.0, factor))
    return {
        key: _lerp_value(first_uv[key], second_uv[key], factor, key in periodic)
        for key in first_uv
        if key in second_uv
    }


def _lerp_value(first, second, factor, periodic):
    """Interpolate one corner value; only single-tile UV layers wrap through 0/1.

    Colors (and multi-tile or open-chain UVs) lerp component-wise with no wrap.
    factor 0 returns ``first`` exactly via Vector.lerp, which is what a count
    stepped down and back up relies on to land on the stored value bit-for-bit.
    """
    if factor >= 1.0:
        return second.copy()
    if periodic:
        return _lerp_uv(first, second, factor)
    return first.lerp(second, factor)


def _lerp_uv(first, second, factor):
    """Lerp two corner UVs known to wrap, stepping over the texture's 0/1 seam.

    A closed strip whose texture wraps stores something like 0.99 and 0.01 on
    the face crossing the seam, and a plain lerp sweeps back through 0.5.
    Landing exactly on an endpoint still returns the stored value, so stepping a
    count down and back up restores the source bit for bit.  ``_lerp_value``
    already owns the non-wrapping case.
    """
    if factor >= 1.0:
        return second.copy()
    return Vector(
        (
            _lerp_wrapped(first.x, second.x, factor),
            _lerp_wrapped(first.y, second.y, factor),
        )
    )


def _lerp_wrapped(first, second, factor):
    if abs(second - first) <= 0.5:
        return first + (second - first) * factor
    return first + (second + (1.0 if second < first else -1.0) - first) * factor


def _u_span(values, closed):
    """Smallest arc covering every value, as a (start, end) pair that may wrap."""
    ordered = sorted(set(values))
    if not ordered:
        return 0.0, 0.0
    if len(ordered) < 2 or not closed:
        return ordered[0], ordered[-1]
    gaps = [
        (ordered[(index + 1) % len(ordered)] - ordered[index]) % 1.0
        for index in range(len(ordered))
    ]
    widest = max(range(len(gaps)), key=lambda index: (gaps[index], -index))
    return ordered[(widest + 1) % len(ordered)], ordered[widest]


def _u_center(start, end, closed):
    """Midpoint of a u arc, accounting for a wrap through 1.0."""
    if closed and end < start:
        end += 1.0
    center = (start + end) * 0.5
    return center % 1.0 if closed else center
