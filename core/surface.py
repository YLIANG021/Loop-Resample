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

One case interpolation cannot answer: a rail vertex an island boundary leaves through
keeps *two* corners at one u, and closing the ring stitches both into the same chain,
so the chain is a function of u that has to pick one.  It always picks the one reached
from below, which is right for the face ending there and a whole island away from the
face starting there -- that face reads a chord across the map.  So a corner standing on
such a vertex takes the value the matched source face stores there, which is the copy
its own island has; see :func:`_tied_corner`.

A boundary with no seam mark on it cannot be answered this way, because no rebuilt
vertex stands there at all.  Those are reported to the user and nothing else: reading
a UV may change what the add-on says, never how the band is wired.
"""

import time
from bisect import bisect_left

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

# How close to a source rail vertex a rebuilt corner has to be before it counts as
# standing on that vertex.  A pinned corner is the same coordinate to within projection
# noise; a corner the sampler moved is somewhere the source never was, and a wider net
# here would hand it a stored value that belongs to its neighbour.
_TIED_CORNER_TOLERANCE = 1e-6

# Where the two things a step asks for hundreds of times but never changes wait between
# the asks: one source face's footprint split at the seam, and one chain's knots with the
# wrap-around copy appended.  Both hang off dicts the capture built once and writes never
# again, and ``_freeze_region`` hands ``source_faces`` to the next step as it stands, so
# the same objects -- and what is cached on them -- ride out the whole session.
_RECORD_ARCS = "arcs"
_CHAIN_POINTS = "points"
_CHAIN_KNOT_US = "us"

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
    is_fan = region.get("kind") == "FAN"
    pole_vertex = region.get("pole_vertex")
    pole_uv = None
    if is_fan and pole_vertex:
        # Find the UV of the pole vertex from any source face that contains it.
        # The pole sits at the center of all its triangles in UV space.
        for face in region["faces"]:
            if not face.is_valid:
                continue
            for loop in face.loops:
                if loop.vert is pole_vertex:
                    pole_uv = loop[bm.loops.layers.uv.active].uv.copy()
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
        # Store pole UV in record for special handling during apply
        record_pole_uv = pole_uv
        records.append(
            {
                "material_index": int(face.material_index),
                "smooth": bool(face.smooth),
                "u_start": start,
                "u_end": end,
                "u_center": center,
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
    # Only now that every face is in can a rail say which of its u values carry more
    # than one corner, so the faces keep their raw corners until this point.
    doubled = [builder.doubled_parameters() for builder in builders]
    for record in records:
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
    unmarked_cuts = _unmarked_boundaries(
        region, doubled, inner_vertices, outer_vertices,
        inner_segments, outer_segments,
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
        # Where an island boundary leaves the band with no seam mark on it, which the
        # transfer cannot repair and the user can; see :func:`_unmarked_boundaries`.
        "unmarked_cuts": unmarked_cuts,
    }


def _unmarked_boundaries(
    region, doubled, inner_vertices, outer_vertices, inner_segments, outer_segments
):
    """Rail vertices an island boundary splits, on which no seam mark stands.

    A seam mark is what puts a rebuilt vertex on the cut, and without one a face has
    to cover both islands at once -- no choice of corner values makes that face small,
    so it is drawn as a chord across the map.  :func:`_tied_corner` fixes the copy a
    pinned vertex reads; nothing here can.  Which boundaries are split comes from the
    stored corner values, but only to decide *what to say*: this reaches no waypoint,
    no anchor and no vertex position, exactly so that editing a UV map cannot move the
    mesh.
    """
    marked = {
        vertex
        for face in region["faces"]
        if face.is_valid
        for edge in face.edges
        if getattr(edge, "seam", False)
        for vertex in edge.verts
    }
    cuts = []
    for rail, (values, vertices, segments) in enumerate(
        (
            (doubled[0], inner_vertices, inner_segments),
            (doubled[1], outer_vertices, outer_segments),
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

    def doubled_parameters(self):
        """The u values this rail holds more than one corner at.

        That is where an island boundary leaves the rail: one mesh vertex, two
        corners with different values, and a chain -- which is a function of u --
        can only answer one of them.  Every source face that stands on such a
        vertex is asked which copy is its own; see :func:`_tied_corner`.
        """
        seen = set()
        doubled = set()
        for key in self._parent:
            if key[0] in seen:
                doubled.add(key[0])
            seen.add(key[0])
        return frozenset(doubled)

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
        record_pole_uv = record.get("pole_uv")
        probes = [] if DIAGNOSE_UV else None
        for loop, rail, u, corner_index in corners:
            # Skip pole vertices - handled separately below
            if rail == -1:
                continue
            chain_index = chains.get(rail)
            if chain_index is None:
                continue
            position = center if u is None else u
            sample = _tied_corner(record, rail, position, closed)
            if sample is None:
                sample = _sample_chain(
                    rails[rail][chain_index], position, periodic, probes
                )
            elif DIAGNOSE_UV:
                probes.append(
                    {
                        "u": position,
                        "low": position,
                        "high": position,
                        "clamped": False,
                        "tied": True,
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
        # Handle pole vertices for FAN regions
        if is_fan and record_pole_uv is not None:
            for loop in face.loops:
                if loop.vert is pole_vertex:
                    for key, (kind, layer) in layers_by_key.items():
                        if kind == "uv":
                            loop[layer].uv = record_pole_uv
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
        overlap = _arc_overlap(span, _record_arcs(record, closed))
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
        overlap = _arc_overlap(span, _record_arcs(record, closed))
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


def _record_arcs(record, closed):
    """A source face's footprint along the rail, split at the seam once per session.

    Every rebuilt face asks every source face for this, so a band of 200 faces over 100
    source faces asks 20,000 times for 100 answers.  ``closed`` comes off the same
    capture the record does, which is the only reason one key is enough: a record cannot
    be reached with a different ``closed`` than the one its footprint was split under.
    """
    arcs = record.get(_RECORD_ARCS)
    if arcs is None:
        arcs = _arc_pieces(record["u_start"], record["u_end"], closed)
        record[_RECORD_ARCS] = arcs
    return arcs


def _arc_overlap(first, second):
    return sum(
        max(0.0, min(high_a, high_b) - max(low_a, low_b))
        for low_a, high_a in first
        for low_b, high_b in second
    )


def _tied_corner(record, rail, u, closed):
    """What the matched source face stores on this rail vertex, if it stores anything.

    Only corners standing on a doubled u are answered here, and ``u`` comes off the
    rebuilt rail, so it is matched by distance: inside the tolerance the two are the
    same vertex, and outside it the corner sits where the source never was, where
    interpolating is the only answer there is.  Asking the face this one was matched
    to -- rather than the chain -- is what makes the answer come out as the copy this
    face's own island keeps there.
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


def _chain_points(chain):
    """A chain's knots, with the wrap-around copy a closed rail needs already on the end.

    A chain that runs all the way around a closed rail continues from its last knot into
    its first across u=1, and saying so costs a fresh list of every knot on the chain --
    once per sampled corner, which is several hundred times a step for a list that was
    settled when the capture finished.
    """
    points = chain.get(_CHAIN_POINTS)
    if points is None:
        knots = chain["knots"]
        points = (
            knots + [(knots[0][0] + 1.0, knots[0][1])] if chain["closed"] else knots
        )
        chain[_CHAIN_POINTS] = points
    return points


def _chain_knot_us(chain):
    """The knot positions of :func:`_chain_points`, ascending.

    Ascending is what lets one jump replace the walk from the front.  It holds because
    ``_RailBuilder.chains`` sorted the knots and every u is a position along the rail,
    so the wrap copy -- the first knot plus a whole turn -- lands past the last one.
    """
    us = chain.get(_CHAIN_KNOT_US)
    if us is None:
        us = [point[0] for point in _chain_points(chain)]
        chain[_CHAIN_KNOT_US] = us
    return us


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
    points = _chain_points(chain)
    if chain["closed"] and u < points[0][0]:
        u += 1.0
    # ``bisect_left`` counts the knots strictly below u, so one less is the knot the walk
    # stopped on: the walk advanced exactly while u was past the *next* knot, which is the
    # same as saying the knot at or below u is the last one it passed.  Both ends clamp --
    # a u before the first knot has no segment ahead of it, and the walk could never reach
    # past the last segment, which is the one a u beyond the end knot falls back on.
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
