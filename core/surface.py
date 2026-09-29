"""Per-source-face shading and loop UV transfer.

A rebuilt face is matched to the source face that held the same place along the
region and inherits its material and shading.  UVs travel on per-rail chains:
one rail's source corners sorted by u, where corners disagreeing at the same u
start a new chain.  A chain is one island's continuous polyline along the rail,
so sampling the matched source face's chain keeps neighbouring rebuilt faces in
agreement at shared vertices while an island boundary still cuts them apart.
Chains split on every stored value, a wider edge set than seams cuts the band
on: a disagreement reaches the geometry only through a mark the user drew or a
UV that parts, while a corner differing only in color changes nothing about
where vertices go and everything about what they inherit.  Corner colors, byte
and float layers alike, travel the same chains and split the same way, so a
color change survives where it coincides with a UV seam; only UV layers are
treated as periodic.  Only two v values ever occur, 0 on the inner rail and 1
on the outer, so sampling a face reduces to interpolating along its corner's
rail.

One case interpolation cannot answer: a rail vertex whose stored values
disagree keeps two corners at one u, and closing the ring stitches both into
the same chain, so the chain, a function of u, has to pick one.  It always
picks the copy reached from below, right for the face ending there and a whole
island away from the face starting there, which would read a chord across the
map.  So a corner on such a vertex takes the value the matched source face
stores there, the copy its own island keeps; see _tied_corner.  A tie only
colors disagree on resolves by the same lookup and costs nothing but the read:
both copies carry one UV, and the face gets its own color either way.

A boundary with no seam mark used to be unanswerable: no rebuilt vertex stood
there.  island_boundary_edges now hands those to seams, which pins a vertex on
one as on a marked one.  A boundary no crossing reaches is reported to the
user: the transfer can move a vertex onto a cut, but only a cut crossing the
band says where to put one.
"""

import time
from bisect import bisect_left

from mathutils import Vector

from .attributes import _u_distance
from .diagnostics import (
    accumulate_scan,
    print_uv_faces,
    print_uv_note,
    print_uv_records,
    print_uv_region,
)
from .regions import region_rails

_UV_MERGE_DECIMALS = 6

# A pinned corner sits on its source rail vertex to within projection noise; a corner
# the sampler moved is somewhere the source never was, and a wider net would hand it a
# neighbour's stored value.
_TIED_CORNER_TOLERANCE = 1e-6

# Knots closer than this along a rail are one position, so a query landing on them
# chooses between copies of a point rather than interpolating.
_CUT_KNOT_TOLERANCE = 1e-9

# Caches on dicts the capture builds once and never writes again: a source face's
# footprint split at the seam per rail, a chain's knots with the wrap-around copy
# appended, the two island ends a chain's cut column separates.  ``_freeze_region`` hands
# ``source_faces`` to the next step as it stands, so the same objects and their caches
# ride out the session.
_RECORD_ARCS = "arcs"
_RECORD_OUTER_ARCS = "outer_arcs"
_CHAIN_POINTS = "points"
_CHAIN_KNOT_US = "us"
_CHAIN_CUT = "cut_ends"

# The [uvdiag] block in ``diagnostics`` collects the votes and per-face probes that
# nothing deciding a UV reads, so flipping this cannot change a value, only what the
# console hears.  Set True, with ``diagnostics.DIAGNOSTICS``, to bring the lines back.
DIAGNOSE_UV = True


def _corner_layers(bm):
    """Every per-corner value the pipeline carries, keyed by ``(kind, name)``.

    A corner color is a 4-component Vector assigned directly to the layer; a UV
    is a struct with a ``.uv`` field.
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


def _uv_corner_layers(bm):
    """The UV subset of ``_corner_layers``: only UVs decide where the band is cut open.

    The transfer needs the whole set, because a painted corner that disagrees
    with its neighbour is still a value a rebuilt face has to inherit from one
    copy or the other.  Whether a disagreement is worth a *vertex* has only two
    answers: a mark the user drew, and a UV that parts.
    """
    return {
        key: layer for key, layer in _corner_layers(bm).items() if key[0] == "uv"
    }


def corner_signature(values):
    """The per-corner values of one loop, rounded to the step every comparison uses.

    ``_RailBuilder`` keys a rail corner by the whole set and
    ``island_boundary_edges`` compares an edge's two faces by its UV entries
    only; one definition of the rounding is what makes "these corners differ"
    mean the same thing in both.
    """
    return tuple(
        (
            key,
            tuple(round(component, _UV_MERGE_DECIMALS) for component in value),
        )
        for key, value in sorted(values.items())
    )


def _loop_values(loop, layers):
    """Every corner value one loop stores, in the shape ``corner_signature`` wants."""
    values = {}
    for key, (kind, layer) in layers.items():
        values[key] = loop[layer].uv if kind == "uv" else loop[layer]
    return values


def island_boundary_edges(edges, bm):
    """Edges whose two faces store different UVs for the same vertex.

    The marked seam and the stored corners disagree on any mesh whose seams were
    never marked or were marked somewhere else, and the transfer reads the
    corners.  A rebuilt face is handed one source face's corner values, so a
    face covering both sides of a disagreement reads a chord across the map;
    ``seams`` therefore asks for these next to the marked ones, same test and
    same rounding, so a boundary this cannot see the chain splitting cannot see
    either.

    UVs alone.  A color that disagrees across an edge splits a chain and each
    side keeps its own color, but no island parts and the user drew no line, so
    a pinned vertex there buys nothing and costs the extra faces around it.

    With no UV layer nothing disagrees: a mesh without a UV map, the common
    case, gains no boundary here and no pinning.
    """
    layers = _uv_corner_layers(bm)
    if not layers:
        return ()
    corners = {}
    boundaries = []
    for edge in edges:
        faces = edge.link_faces
        if len(faces) != 2:
            continue
        stored = []
        for face in faces:
            map_for_face = corners.get(face)
            if map_for_face is None:
                map_for_face = {
                    loop.vert: corner_signature(_loop_values(loop, layers))
                    for loop in face.loops
                }
                corners[face] = map_for_face
            stored.append(map_for_face)
        first, second = stored
        if any(
            first[vertex] != second[vertex] for vertex in edge.verts
        ):
            boundaries.append(edge)
    return tuple(boundaries)


def capture_region_faces(bm, region, paths):
    """Record every source face as shading plus the region's two rail chains.

    A face with no corner on the inner rail (an outer row of a region deeper
    than one quad) is left out: the rebuild collapses such rows into a single
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
    is_fan = region.get("kind") == "FAN"
    pole_vertex = region.get("pole_vertex")
    pole_uv = None
    active_uv = bm.loops.layers.uv.active
    if is_fan and pole_vertex and active_uv is not None:
        # The pole sits at the center of all its triangles in UV space, so any source
        # face containing it gives its UV.  A mesh never unwrapped has no active layer
        # and no pole UV to carry; the transfer below reads that as "skip the UV corner".
        for face in region["faces"]:
            if not face.is_valid:
                continue
            for loop in face.loops:
                if loop.vert is pole_vertex:
                    pole_uv = loop[active_uv].uv.copy()
                    break
            if pole_uv is not None:
                break

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
            elif is_fan and vertex is pole_vertex:
                # Pole vertex: mark specially, don't add to rail chains
                rail, u = -1, None
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
        # The face's place along the rail the vote does not read, taken before the centre
        # fills in the corners on neither rail.  The inner rail does not always hold the
        # answer: a face the inner vote cannot separate is placed by this instead; see
        # _match_face.
        outer_us = [
            corner["u"]
            for corner in corners
            if corner["rail"] == 1 and corner["u"] is not None
        ]
        outer_span = _u_span(outer_us, closed) if outer_us else None
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
        record_pole_uv = pole_uv
        records.append(
            {
                "material_index": int(face.material_index),
                "smooth": bool(face.smooth),
                "u_start": start,
                "u_end": end,
                "u_center": center,
                "outer_span": outer_span,
                "face_index": face.index,
                "chains": chains,
                "corners": {
                    (corner["rail"], corner["u"]): corner["values"]
                    for corner in corners if corner["rail"] >= 0
                },
                "pole_uv": record_pole_uv,
            }
        )

    rails = []
    indices = []
    for builder in builders:
        chain_list, index = builder.chains()
        rails.append(chain_list)
        indices.append(index)
    # Only once every face is in can a rail say which u values carry more than one
    # corner, so the records keep their raw corners until here.
    doubled = [builder.doubled_parameters() for builder in builders]
    for order, record in enumerate(records):
        chains = {}
        for rail, token in record["chains"].items():
            chains[rail] = (
                None
                if token is None
                else indices[rail][builders[rail]._find(token)]
            )
        record["chains"] = chains
        record["tied"] = {
            position: values
            for position, values in record.pop("corners").items()
            if position[1] in doubled[position[0]]
        }
        if DIAGNOSE_UV:
            # The order the vote walks, which used to break ties; the dump names
            # candidates by it.
            record["diag_id"] = order
    unmarked_cuts = _unmarked_boundaries(
        region,
        [builder.uv_doubled_parameters() for builder in builders],
        inner_vertices,
        outer_vertices,
        inner_segments,
        outer_segments,
    )
    if DIAGNOSE_UV and unmarked_cuts:
        print_uv_note(
            region,
            "unmarked-cut "
            + " ".join(f"r{rail}v{index}" for rail, index in unmarked_cuts),
        )
    return {
        "closed": closed,
        "records": records,
        "rails": rails,
        "periodic": _periodic_layers(bounds, closed),
        # Island boundaries leaving the band on no rebuilt vertex: the transfer cannot
        # repair these, the user can; see _unmarked_boundaries.
        "unmarked_cuts": unmarked_cuts,
    }


def _unmarked_boundaries(
    region, uv_doubled, inner_vertices, outer_vertices, inner_segments, outer_segments
):
    """Rail vertices an island boundary splits that no crossing was built on.

    Only a crossing puts a rebuilt vertex on the cut, and ``seams`` now reads
    crossings off a mark or a parted UV, so a cut neither reaches leaves a face
    covering both islands at once, drawn as a chord across the map that no
    choice of corner values makes smaller.  The closing note counts those.

    The set handed in is the UV one, not the wider ``doubled_parameters``,
    because the note's advice is "mark a seam here".  A u doubling only on a
    painted color already transfers every corner its own face stores, has no
    boundary a mark could line up with, and would be reported as a defect the
    user cannot fix.  Which boundaries split still comes from the stored values,
    and only to decide what to say: this reaches no waypoint, no anchor and no
    vertex position.
    """
    marked = {
        vertex
        for face in region["faces"]
        if face.is_valid
        for edge in face.edges
        if getattr(edge, "seam", False)
        for vertex in edge.verts
    }
    for crossing in region.get("seam_crossings") or ():
        for vertices, index in (
            (inner_vertices, crossing["inner_index"]),
            (outer_vertices, crossing["outer_index"]),
        ):
            # A fan's pole is a rail to ``seams`` but not to this capture, which reads
            # corners off the two vertex rails only.
            if index < len(vertices):
                marked.add(vertices[index])
    cuts = []
    for rail, (values, vertices, segments) in enumerate(
        (
            (uv_doubled[0], inner_vertices, inner_segments),
            (uv_doubled[1], outer_vertices, outer_segments),
        )
    ):
        if not values:
            continue
        # A rail with no vertices is a fan's pole, whose corners sit at their own
        # face's centre and so never share a u with each other: nothing doubles there.
        count = segments or 1
        cuts.extend(
            (rail, vertex.index)
            for index, vertex in enumerate(vertices)
            if index / count in values and vertex not in marked
        )
    return tuple(cuts)


class _RailBuilder:
    """One rail's source corners, merged into continuous per-island chains.

    Corners sharing a u and a UV value become one knot; every source face edge
    along the rail stitches two knots together, so a corner whose UV disagrees
    with its neighbour's splits into two knots nothing stitches, which is what
    keeps islands apart.
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

    def doubled_parameters(self):
        """The u values this rail holds more than one corner at.

        There a stored value has to be chosen rather than interpolated: one
        vertex, two corners, and a chain (a function of u) answers only one.
        Every source face on such a vertex is asked which copy is its own; see
        _tied_corner.
        """
        seen = set()
        doubled = set()
        for key in self._parent:
            if key[0] in seen:
                doubled.add(key[0])
            seen.add(key[0])
        return frozenset(doubled)

    def uv_doubled_parameters(self):
        """The u values this rail holds more than one *UV* at.

        ``doubled_parameters`` is wider: corners differing only in color are two
        knots and double a u there, yet no island parts and no crossing was
        asked to pin one.  Only this narrower answer backs the closing note's
        claim that a face at the position it names reads a chord across the
        texture map.
        """
        first = {}
        doubled = set()
        for key in self._parent:
            signature = corner_signature(
                {
                    name: value
                    for name, value in self._values[key].items()
                    if name[0] == "uv"
                }
            )
            u = key[0]
            if u not in first:
                first[u] = signature
            elif first[u] != signature:
                doubled.add(u)
        return frozenset(doubled)

    def _key(self, corner):
        return (corner["u"], corner_signature(corner["values"]))

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

    A layer spread over several tiles is an atlas offset; its period is unknown
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
        # Rebuild already stamped the region defaults and there is nothing to
        # interpolate from.
        return
    closed = bool(captured.get("closed"))
    is_fan = region.get("kind") == "FAN"
    pole_vertex = region.get("pole_vertex")
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
    if DIAGNOSE_UV and records and "diag_id" in records[0]:
        # A mesh with no active UV layer still has corner values to dump; only the UV
        # column has nothing to name.
        uv_key = ("uv", uv_layer.name) if uv_layer is not None else None
        print_uv_records(region, records, rails, uv_key)
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
        outer_span = _u_span(outer_us, closed) if outer_us else None
        vote = {} if DIAGNOSE_UV else None
        record = _match_face(records, start, end, closed, vote, outer_span)
        off_island = not _island_reaches(record, corner_us, rails)
        if off_island:
            record = (
                _match_island(records, start, end, closed, corner_us, rails)
                or record
            )
        face.material_index = record["material_index"]
        face.smooth = record["smooth"]
        chains = record["chains"]
        record_pole_uv = record.get("pole_uv")
        probes = [] if DIAGNOSE_UV else None
        for loop, rail, u, corner_index in corners:
            # Pole vertices are handled below.
            if rail == -1:
                continue
            chain_index = chains.get(rail)
            if chain_index is None:
                continue
            position = center if u is None else u
            sample = _tied_corner(record, rail, position, closed)
            if sample is None:
                sample = _sample_chain(
                    rails[rail][chain_index], position, periodic, probes, corner_us[rail]
                )
            elif DIAGNOSE_UV:
                probes.append(
                    {
                        "u": position,
                        "low": position,
                        "high": position,
                        "clamped": False,
                        "tied": True,
                        "side": 0,
                    }
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
        if is_fan and record_pole_uv is not None:
            for loop in face.loops:
                if loop.vert is pole_vertex:
                    for key, (kind, layer) in layers_by_key.items():
                        if kind == "uv":
                            loop[layer].uv = record_pole_uv
        if DIAGNOSE_UV:
            votes = _diag_votes(records, ((start, end), outer_span), closed)
            rows.append(
                {
                    "face_index": face.index,
                    "face_seq": len(rows),
                    "record_id": record.get("diag_id"),
                    "votes": votes,
                    "votes_diverge": bool(
                        votes
                        and votes["inner"]["ranked"][0][0]
                        != votes["outer"]["ranked"][0][0]
                    ),
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
                    "outer_span": outer_span,
                    "record_start": record["u_start"],
                    "record_end": record["u_end"],
                    "record_center": record["u_center"],
                    "overlap": vote["overlap"],
                    "tied": vote["tied"],
                    "fallback": vote["fallback"],
                    "resolved": vote["resolved"],
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

    A crossing sits on a column boundary, so this flags the faces on both sides
    of it, the neighborhood where a wrong island can be sampled from.
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

    A rebuilt face sits inside a single island, named by the pair of chains, one
    per rail, never either alone.  Taking a record whose chain cannot reach a
    corner clamps that corner onto a knot that is not its own: both rails losing
    the same way collapses the face to a line along the seam, one rail losing
    stretches a wire across the UV map to the other island.
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

    Only consulted once the overlap vote has been rejected.  A triangle step has
    a single inner corner, so its inner span is a point that overlaps nothing
    and the vote falls back to the outer coverage and the nearest centre, which
    can still land across the seam and hand back the neighbouring island's
    corner set.  Overlap still ranks, so a face that does cover a source face
    keeps following that one.
    """
    span = _arc_pieces(start, end, closed)
    center = _u_center(start, end, closed)
    best = None
    best_key = None
    for record in records:
        if not _island_reaches(record, corner_us, rails):
            continue
        overlap = _arc_overlap(span, _record_arcs(record, closed))
        key = (-overlap, _u_distance(record["u_center"], center, closed), record["face_index"])
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
        # The chain wraps through 0/1: its arc runs from the first knot to that knot plus
        # one, and a u below the start is read one turn later, as _sample_chain does it.
        # Judging against the last knot would call it reachable in the wrong direction.
        high = low + 1.0
        if u < low:
            u += 1.0
    return low - 1e-9 <= u <= high + 1e-9


def _diag_votes(records, spans, closed):
    """The best and second-best source face along each rail, ranked as the real vote ranks.

    The vote reads the inner rail first and the outer only when the inner cannot
    separate the candidates, so per-rail rankings expose what those lines hide:
    a rebuilt face whose two rails point at different source faces is reading
    both sides of the island's cut at once, and that draws a face as a chord
    across its own island.  When a rail's corners all stand at one u (the face a
    triangle step left behind), no overlap is won and the choice falls through
    to the outer coverage and the nearest centre, so ``centre`` ranks those same
    candidates by that distance too.
    """
    if not records or "diag_id" not in records[0]:
        return None
    center = _u_center(spans[0][0], spans[0][1], closed)
    votes = {}
    for rail, face_span in enumerate(spans):
        span = () if face_span is None else _arc_pieces(*face_span, closed)
        pairs = sorted(
            (
                (
                    record["diag_id"],
                    _arc_overlap(
                        span,
                        _record_arcs(record, closed)
                        if rail == 0
                        else _record_outer_arcs(record, closed),
                    ),
                )
                for record in records
            ),
            key=lambda pair: (-pair[1], pair[0]),
        )
        entry = {
            "ranked": pairs[:2],
            "ties": sum(1 for _, overlap in pairs if overlap == pairs[0][1]),
            # How much the winner won by: two candidates can print the same overlap and
            # still be ranked, so this says whether the choice was a decision or a coin
            # flip the record order settled.
            "gap": pairs[0][1] - pairs[min(1, len(pairs) - 1)][1],
        }
        if rail == 0 and pairs[0][1] <= 0.0:
            # Nothing was covered on this rail, so the vote went to the outer coverage
            # and the centre distance; rank those same candidates by it too.
            centre = sorted(
                (
                    (
                        record["diag_id"],
                        _u_distance(record["u_center"], center, closed),
                    )
                    for record in records
                ),
                key=lambda pair: (pair[1], pair[0]),
            )[:2]
            entry["centre"] = centre
            entry["centre_gap"] = centre[min(1, len(centre) - 1)][1] - centre[0][1]
        votes["inner" if rail == 0 else "outer"] = entry
    return votes


_MATCH_TIE_TOLERANCE = 1e-12
"""How close two inner overlaps have to be to count as the same answer.

Evenly spaced rails make this common: a rebuilt face straddling two source
columns covers each by the same width and the two overlaps come out equal to
within a float.  1e-12 sits nine orders below the smallest real column on a
200-segment band and four above the noise those columns produce, so it flags a
coin flip without merging a decision.
"""


def _match_face(records, start, end, closed, probe=None, outer=None):
    """The source face the rebuilt face mostly covers along the region.

    Once counts change, a rebuilt face can straddle a material or shading
    boundary; a centre-only vote flips the whole face to whichever side the
    centre lands on, while the overlap majority follows the source face
    actually covered most.

    The inner overlap alone is not always a decision.  When it is not, the
    answer used to come from whichever candidate the walk reached first, an
    order that changes between Blender sessions and can be the wrong side of an
    island's cut.  So every source face within _MATCH_TIE_TOLERANCE of the best
    is kept and re-ranked: outer coverage first (the rail corner values are read
    from too), then nearest centre (the rule a degenerate inner span always
    needed), then the source face index, which settles an exact tie the same way
    every time.

    ``probe`` is the UV diagnostic's dict, read by nothing else: it learns
    whether the vote was won outright, how many source faces tied for it, and
    which rule settled it.
    """
    started = time.perf_counter()
    span = _arc_pieces(start, end, closed)
    best = None
    best_overlap = 0.0
    runner_overlap = 0.0
    positive = 0
    for record in records:
        overlap = _arc_overlap(span, _record_arcs(record, closed))
        if overlap > best_overlap:
            best, runner_overlap = record, best_overlap
            best_overlap = overlap
        elif overlap > runner_overlap:
            runner_overlap = overlap
        if overlap > 0.0:
            positive += 1
    work = len(records)
    fallback = best is None
    resolved = "inner"
    if fallback or best_overlap - runner_overlap <= _MATCH_TIE_TOLERANCE:
        center = _u_center(start, end, closed)
        outer_pieces = _arc_pieces(*outer, closed) if outer else ()
        ranked = sorted(
            (
                (
                    -_arc_overlap(outer_pieces, _record_outer_arcs(record, closed)),
                    _u_distance(record["u_center"], center, closed),
                    record["face_index"],
                    record,
                )
                for record in records
                if _arc_overlap(span, _record_arcs(record, closed))
                >= best_overlap - _MATCH_TIE_TOLERANCE
            ),
        )
        work += len(ranked)
        resolved = (
            "outer"
            if ranked[0][0] < 0.0 and (len(ranked) < 2 or ranked[1][0] > ranked[0][0])
            else "centre"
        )
        best = ranked[0][3]
    if probe is not None:
        probe["overlap"] = best_overlap
        probe["tied"] = max(0, positive - 1)
        probe["fallback"] = fallback
        probe["resolved"] = resolved
    accumulate_scan("face-match", time.perf_counter() - started, work)
    return best


def _arc_pieces(start, end, closed):
    """One u arc as at most two non-wrapping (low, high) pieces."""
    if not closed or end >= start:
        return [(start, end)]
    return [(start, 1.0), (0.0, end)]


def _record_arcs(record, closed):
    """A source face's footprint along the rail, split at the seam once per session.

    Every rebuilt face asks every source face for this, thousands of times a
    step for a few hundred answers.  ``closed`` comes off the same capture the
    record does, so one key is enough: a record is never reached under a
    different ``closed`` than its footprint was split with.
    """
    arcs = record.get(_RECORD_ARCS)
    if arcs is None:
        arcs = _arc_pieces(record["u_start"], record["u_end"], closed)
        record[_RECORD_ARCS] = arcs
    return arcs


def _record_outer_arcs(record, closed):
    """A source face's footprint along the outer rail, split the way the inner one is.

    Only the faces the inner vote could not separate ask for this, so a healthy band
    never computes it.
    """
    span = record.get("outer_span")
    if span is None:
        return ()
    arcs = record.get(_RECORD_OUTER_ARCS)
    if arcs is None:
        arcs = _arc_pieces(span[0], span[1], closed)
        record[_RECORD_OUTER_ARCS] = arcs
    return arcs


def _arc_overlap(first, second):
    return sum(
        max(0.0, min(high_a, high_b) - max(low_a, low_b))
        for low_a, high_a in first
        for low_b, high_b in second
    )


def _tied_corner(record, rail, u, closed):
    """What the matched source face stores on this rail vertex, if it stores anything.

    Only corners on a doubled u are answered here, and ``u`` comes off the
    rebuilt rail, so it is matched by distance: inside the tolerance the two are
    the same vertex; outside it the corner sits where the source never was and
    interpolating is the only answer.  Asking the matched face rather than the
    chain is what returns the copy this face's own island keeps there.
    """
    tied = record["tied"]
    if not tied:
        return None
    best = None
    best_distance = _TIED_CORNER_TOLERANCE
    for (tied_rail, tied_u), values in tied.items():
        if tied_rail != rail:
            continue
        distance = _u_distance(u, tied_u, closed)
        if distance < best_distance:
            best, best_distance = values, distance
    return best


def _chain_cut(chain):
    """The two ends of the island a chain's cut column separates, worked out once.

    Where the rail walk arrives at one uv and leaves from another, the chain
    holds that u twice, and the walk can cross the seam anywhere along the rail,
    not only at the chain's lowest u.  Sorting cannot say which copy starts the
    island and which ends it (both sit at the same u), so the island is asked:
    the copy nearer the knot the chain moves on to starts it, the copy nearer
    the knot the chain comes back to ends it.  Neither is a close call, a cut
    column sitting a whole island's width from its own far end; of several such
    columns in one chain, the pair farthest apart separates the island.  None
    means nothing to route: no column held twice, or a chain too short to have a
    side to come back to.
    """
    if _CHAIN_CUT not in chain:
        knots = chain["knots"]
        columns = []
        for knot in knots:
            if columns and abs(columns[-1][-1][0] - knot[0]) <= _CUT_KNOT_TOLERANCE:
                columns[-1].append(knot)
            else:
                columns.append([knot])
        ends = None
        widest = 0.0
        for index, column in enumerate(columns):
            if len(column) < 2 or len(knots) - len(column) < 2:
                continue
            # The walk leaves the cut for the next column up the rail and comes back to
            # it from the column below; a cut with no column below is met one turn on,
            # from the chain's last knot.
            ahead = columns[(index + 1) % len(columns)][0]
            behind = columns[index - 1][-1]
            head = min(column, key=lambda knot: _uv_distance(knot[1], ahead[1]))
            tail = min(column, key=lambda knot: _uv_distance(knot[1], behind[1]))
            if head is tail:
                continue
            distance = _uv_distance(head[1], tail[1])
            if ends is None or distance > widest:
                ends, widest = (head, tail), distance
        chain[_CHAIN_CUT] = ends
    return chain[_CHAIN_CUT]


def _chain_points(chain):
    """A chain's knots, with the wrap-around copy a closed rail needs already on the end.

    A closed rail's chain continues from its last knot into its first across
    u=1; building that per sample would cost a fresh list several hundred times
    a step for one settled when the capture finished.

    At the island's own cut the chain holds two copies of one u, and continuing
    from the first would jump across the island to where the walk started.  So
    the chain starts at the cut instead: one copy stays at the front, knots
    above the cut keep their u, knots below it (reached only after the walk
    comes around the rail's origin) take a whole turn, and the far copy closes
    the list one turn on.  That is the order the island is really walked in; a
    cut at the lowest u leaves the batch below it empty.
    """
    points = chain.get(_CHAIN_POINTS)
    if points is None:
        knots = chain["knots"]
        ends = _chain_cut(chain) if chain["closed"] else None
        if ends is None:
            points = (
                knots + [(knots[0][0] + 1.0, knots[0][1])] if chain["closed"] else knots
            )
        else:
            head, tail = ends
            cut_u = head[0]
            points = [head]
            wrapped = []
            for knot in knots:
                if knot is head or knot is tail:
                    continue
                knot_u, knot_uv = knot
                if knot_u > cut_u + _CUT_KNOT_TOLERANCE:
                    points.append(knot)
                else:
                    wrapped.append((knot_u + 1.0, knot_uv))
            points.extend(wrapped)
            points.append((tail[0] + 1.0, tail[1]))
        chain[_CHAIN_POINTS] = points
    return points


def _chain_knot_us(chain):
    """The knot positions of ``_chain_points``, ascending.

    Ascending is what lets one jump replace the walk from the front.  It holds
    because ``_RailBuilder.chains`` sorted the knots and routing only adds a
    whole turn to the batch below the cut; rail us never pass one turn, so that
    batch lands between the last knot above the cut and the far copy closing the
    list.
    """
    us = chain.get(_CHAIN_KNOT_US)
    if us is None:
        us = [point[0] for point in _chain_points(chain)]
        chain[_CHAIN_KNOT_US] = us
    return us


def _corner_side(rail_us, u, closed):
    """Which way a face's other corners on this rail lie from ``u``: +1 ahead, -1 behind.

    A rebuilt face never covers half the loop, so its corners are either all one
    way from the cut or all the other.  Mixed, or nothing to compare against, is
    answered 0: there is no side to read the cut from.
    """
    ahead = False
    behind = False
    for other in rail_us:
        if other is None or abs(other - u) <= _CUT_KNOT_TOLERANCE:
            continue
        delta = other - u
        if closed:
            ahead = ahead or 0.0 < delta < 0.5 or delta < -0.5
            behind = behind or delta > 0.5 or -0.5 < delta < 0.0
        else:
            ahead = ahead or delta > 0.0
            behind = behind or delta < 0.0
    if ahead == behind:
        return 0
    return 1 if ahead else -1


def _uv_distance(first, second):
    total = 0.0
    for key, vector in first.items():
        other = second.get(key)
        if other is None:
            continue
        for value, expected in zip(vector, other):
            total += (value - expected) * (value - expected)
    return total


def _sample_chain(chain, u, periodic, probe=None, rail_us=()):
    """Interpolate one island's rail polyline at u, as {layer name: Vector}.

    ``probe`` is the UV diagnostic's list, read by nothing else: one entry per
    sample giving the u asked for, the u window the chain covers, and whether
    the answer had to be clamped to an end knot.  ``rail_us`` are the face's
    other corners on this rail: a cut column has two copies and they say which
    one this face stands on.
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
                    "side": 0,
                }
            )
        return knots[0][1]
    points = _chain_points(chain)
    if chain["closed"] and u < points[0][0]:
        u += 1.0
    side = 0
    asked = u
    ends = _chain_cut(chain)
    if ends is not None and abs(u - ends[0][0]) <= _CUT_KNOT_TOLERANCE:
        # A face arriving at the cut from the far side of the loop wants the end the walk
        # comes back to, which the chain now carries one turn on rather than at the front.
        side = _corner_side(rail_us, u, chain["closed"])
        if side < 0:
            u += 1.0
    # ``bisect_left`` counts the knots strictly below u, so one less is the knot at or
    # below u, the last one the walk passed.  Both ends clamp: a u before the first knot
    # has no segment ahead of it, and a u past the end knot falls back on the last
    # segment, the one the walk could never pass.
    index = bisect_left(_chain_knot_us(chain), u) - 1
    if index < 0:
        index = 0
    elif index > len(points) - 2:
        index = len(points) - 2
    accumulate_scan("chain-sample", 0.0, index + 1)
    first_u, first_uv = points[index]
    second_u, second_uv = points[index + 1]
    span = second_u - first_u
    factor = 0.0 if span <= 1e-12 else (u - first_u) / span
    if probe is not None:
        probe.append(
            {
                "u": asked,
                "low": points[0][0],
                "high": points[-1][0],
                "clamped": factor < 0.0 or factor > 1.0,
                "side": side,
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
    stepped down and back up relies on to land on the stored value bit for bit.
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
    Landing exactly on an endpoint still returns the stored value.
    ``_lerp_value`` owns the non-wrapping case.
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
