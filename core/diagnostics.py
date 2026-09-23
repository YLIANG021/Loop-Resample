"""Console timing and failure diagnostics for Loop Resample."""

from .utils import _point

_SCAN_TOTALS = {}


def diagnostic_vertex(vertex):
    """Return a stable, copyable vertex description for diagnostics."""
    point = _point(vertex)
    index = getattr(vertex, "index", None)
    return (
        f"index={index if index is not None else '-'} "
        f"co=({point.x:.9g},{point.y:.9g},{point.z:.9g})"
    )


def print_timing(label, elapsed, **details):
    suffix = " ".join(f"{key}={value}" for key, value in details.items())
    print(
        f"[Loop Resample][timing] {label} {elapsed * 1000.0:.3f}ms"
        + (f" {suffix}" if suffix else "")
    )


def accumulate_scan(label, elapsed, work):
    """Add one linear-scan measurement to this step's totals.

    ``work`` counts the inner iterations actually performed, so a faster scan is
    visible as a drop in ``work`` while ``ns_per_work`` stays flat -- that pairing
    is what separates an algorithmic win from a machine that happened to be idle.
    """
    totals = _SCAN_TOTALS.get(label)
    if totals is None:
        _SCAN_TOTALS[label] = [elapsed, work, 1]
        return
    totals[0] += elapsed
    totals[1] += work
    totals[2] += 1


def reset_scans():
    """Drop the totals, so a failed step cannot bleed into the next report."""
    _SCAN_TOTALS.clear()


def print_scans():
    """One line per scan site; ``ms=0`` marks a work-counted site without a timer."""
    for label in sorted(_SCAN_TOTALS):
        elapsed, work, calls = _SCAN_TOTALS[label]
        line = (
            f"[Loop Resample][timing] scan-{label} {elapsed * 1000.0:.3f}ms"
            f" calls={calls} work={work:.0f}"
        )
        if elapsed > 0.0 and work > 0:
            line += f" ns_per_work={elapsed / work * 1e9:.1f}"
        print(line)


def print_seam_crossings(anchors_per_path, counts):
    """Report which source path vertices a seam crossing sits on.

    These are the indices handed to the sampler as pins, so an empty list with a
    non-empty ``seam-rungs`` line means the crossing landed on the outer rail of a
    strip whose inner rail is not a resampled path -- which is the normal case.
    """
    print(
        "[Loop Resample][diagnostic] seam-crossings "
        + " ".join(
            "path{}:{}->{}".format(
                index,
                "[" + ",".join(str(value) for value in sorted(set(anchors))) + "]",
                count,
            )
            for index, (anchors, count) in enumerate(zip(anchors_per_path, counts))
        )
    )


def print_seam_rungs(region, rungs):
    """Report which ladder column each seam crossing took in one rebuilt strip.

    A pair with a second number after it slid: the ladder offered no rung on the column
    the source crossing sat on, so the red line took the nearest one it did.
    """
    taken = []
    for rung in rungs:
        inner, outer = rung["node"]
        taken.append(
            f"{inner}>{outer}"
            if inner == rung["preferred"]
            else f"{inner}>{outer}<{rung['preferred']}"
        )
    print(
        "[Loop Resample][diagnostic] seam-rungs "
        f"region={region.get('region_index')} path={region.get('path_index')} "
        f"rungs={len(rungs)} " + " ".join(taken)
    )


def print_seam_jogs(joins):
    """Report red lines that finished crossing a path by running along it.

    Silent when every crossing found the same path vertex on both sides, which is the
    normal case -- so a missing line is not a missing seam.
    """
    if not joins:
        return
    print(
        "[Loop Resample][diagnostic] seam-jogs "
        + " ".join(
            f"path{path}>vertex{source}:{steps}edge(s)"
            for path, source, steps in joins
        )
    )


def print_seam_crossing_skipped(region, reason, detail):
    """Report a seam crossing that could not become a rung of the ladder."""
    print(
        "[Loop Resample][diagnostic] seam-skip "
        f"region={region.get('region_index')} path={region.get('path_index')} "
        f"reason={reason} {detail}"
    )


def print_crossing(first_label, first_segment, second_label, second_segment, epsilon_squared):
    print(
        "[Loop Resample][diagnostic] crossing "
        f"first={first_label} "
        f"first_start=({diagnostic_vertex(first_segment[0])}) "
        f"first_end=({diagnostic_vertex(first_segment[1])}) "
        f"second={second_label} "
        f"second_start=({diagnostic_vertex(second_segment[0])}) "
        f"second_end=({diagnostic_vertex(second_segment[1])}) "
        f"epsilon_squared={epsilon_squared:.9g}"
    )


def print_degenerate_face(label, face_index, face):
    print(
        f"[Loop Resample][diagnostic] {label} "
        f"face={face_index} size={len(face)} vertices=["
        + "; ".join(diagnostic_vertex(vertex) for vertex in face)
        + "]"
    )


def print_normal_mismatch(face_index, face, alignment):
    print(
        "[Loop Resample][diagnostic] normal-mismatch "
        f"face={face_index} size={len(face)} alignment={alignment:.9g} vertices=["
        + "; ".join(diagnostic_vertex(vertex) for vertex in face)
        + "]"
    )


# --- temporary UV island diagnostic -------------------------------------------
# Added to pin down why a rebuilt face can take its corner values from the wrong
# island.  Everything from this marker to the end of the file stays for now and is
# removed in one go when the add-on is finished; it is gated by
# ``surface.DIAGNOSE_UV``.


def _region_tag(region):
    return (
        f"region={region.get('region_index')} path={region.get('path_index')}"
    )


def print_uv_region(region, rails, crossings, parameters=()):
    """One region's UV inputs: how many islands each rail splits into, and where the seam crosses.

    ``chain`` u ranges are the only window a rebuilt face can be sampled from --
    a face whose u falls outside its chosen chain is clamped to that chain's end
    and visibly hangs off the island instead of landing in it.
    """
    print(
        f"[Loop Resample][uvdiag] {_region_tag(region)} "
        f"source_faces={len(region.get('faces') or ())} "
        f"crossings={len(crossings)}"
    )
    for crossing in crossings:
        print(
            f"[Loop Resample][uvdiag]   seam-crossing "
            f"inner_u={crossing['inner_u']:.6f} outer_u={crossing['outer_u']:.6f}"
        )
    for rail, values in enumerate(parameters):
        print(
            f"[Loop Resample][uvdiag]   rail{rail} rebuilt="
            + " ".join(f"{index}:{value:.6f}" for index, value in enumerate(values))
        )
    for rail, chains in enumerate(rails or ()):
        print(f"[Loop Resample][uvdiag]   rail{rail} chains={len(chains)}")
        for index, chain in enumerate(chains):
            knots = chain["knots"]
            print(
                f"[Loop Resample][uvdiag]     chain{index} knots={len(knots)} "
                f"u=[{knots[0][0]:.6f},{knots[-1][0]:.6f}] "
                f"closed={int(chain['closed'])}"
            )


def print_uv_note(region, detail):
    """A one-line UV fact that has no face to attach to."""
    print(f"[Loop Resample][uvdiag] {_region_tag(region)} {detail}")


def print_uv_faces(region, rows, total):
    """Every rebuilt face the UV transfer could not place cleanly.

    A line is emitted when a corner was clamped to a chain end, when the face fell
    through to the nearest-centre guess, when several source faces tied for it, when
    it sits where a seam crosses, or when the island vote had to replace the face its
    overlap vote picked -- the ways a wrong island can win, and the last one is what
    keeps a wire off the map.
    """
    flagged = [
        row
        for row in rows
        if row["island_vote"]
        or row["fallback"]
        or row["tied"] > 1
        or row["near_seam"]
        or any(probe["clamped"] for probe in row["probes"])
    ]
    print(
        f"[Loop Resample][uvdiag] {_region_tag(region)} faces={total} "
        f"flagged={len(flagged)} "
        f"moved={sum(bool(row['island_vote']) for row in rows)}"
    )
    for row in flagged:
        center = row["center"]
        print(
            f"[Loop Resample][uvdiag] {_region_tag(region)} "
            f"face={row['face_index']} verts=[{row['vertices']}] "
            f"rails={row['corner_rails']} "
            f"at=({center.x:.4f},{center.y:.4f},{center.z:.4f}) "
            f"corners=inner{row['inner_corners']}/outer{row['outer_corners']} "
            f"inner_span=[{row['inner_start']:.6f},{row['inner_end']:.6f}] "
            f"outer_span=[{row['outer_start']:.6f},{row['outer_end']:.6f}] "
            f"record_span=[{row['record_start']:.6f},{row['record_end']:.6f}] "
            f"record_center={row['record_center']:.6f} "
            f"overlap={row['overlap']:.6f} tied={row['tied']} "
            f"fallback={int(row['fallback'])} "
            f"near_seam={int(row['near_seam'])} "
            f"island={int(row['island_vote'])} mat={row['material']} "
            f"uv=[{row['uvs']}] "
            + " ".join(
                f"|r{probe['rail']}v{probe['vertex_index']}chain{probe['chain']} "
                f"u={probe['u']:.6f} in[{probe['low']:.6f},{probe['high']:.6f}]"
                + (" CLAMPED" if probe["clamped"] else "")
                for probe in row["probes"]
            )
        )
