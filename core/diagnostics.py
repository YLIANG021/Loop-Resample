"""Console timing and failure diagnostics for Loop Resample."""

import traceback

from .utils import _point

_SCAN_TOTALS = {}
_STEP = {"base": {}, "scope": {}, "at": "-", "detail": {}}


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


def start_step(**details):
    """Record what a step was asked to do, so a failure can print its own post-mortem.

    ``apply_counts`` turns an exception into a return string, which is what the HUD shows
    and what leaves the system console with nothing but a bare ``operator-failed`` timing:
    the raise itself, and every number the planner was handed, are unrecoverable after it.
    A step therefore carries its own context and prints it the moment it fails.
    """
    _STEP["base"] = details
    _STEP["scope"] = {}
    _STEP["at"] = "start"
    _STEP["detail"] = {}


def start_scope(**details):
    """Give the stages that follow a shared identity -- which region, which path.

    ``at`` becomes ``enter`` rather than keeping the previous scope's last stage, so work
    that dies before its first stage is not blamed on the stage before it.
    """
    _STEP["scope"] = details
    _STEP["detail"] = {}
    _STEP["at"] = "enter"


def mark(label, **details):
    """Note the stage a step just entered; only the last one before a raise is printed."""
    _STEP["at"] = label
    _STEP["detail"] = details


def print_failure(elapsed):
    """The stage a step died in, the data that stage was given, and the traceback."""
    stage = " ".join(
        f"{key}={value}"
        for key, value in {**_STEP["scope"], **_STEP["detail"]}.items()
    )
    print(
        "[Loop Resample][diagnostic] failed"
        f" {elapsed * 1000.0:.3f}ms at={_STEP['at']}" + (f" {stage}" if stage else "")
    )
    print(
        "[Loop Resample][diagnostic] step "
        + " ".join(f"{key}={value}" for key, value in _STEP["base"].items())
    )
    traceback.print_exc()


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


# --- temporary ladder diagnostic ----------------------------------------------
# Added to find which step moved a strip's connectivity while only a shape axis was
# being scrolled.  ``ladder``'s ``gap`` is the margin the search won by, so it says
# whether one rail vertex sliding was ever likely to flip the strip; ``ladder-final``
# shows what actually became faces and what each of its columns' rungs measures,
# because the column pair whose rung lengths cross is the flip itself.
# Gated by ``planner.DIAGNOSE_LADDER`` and removed in one go with the UV block below.

_LADDER_KIND_LETTER = {"QUAD": "Q", "INNER_TRI": "I", "OUTER_TRI": "O"}


def _ladder_sequence(transitions):
    return "".join(_LADDER_KIND_LETTER.get(kind, "?") for kind in transitions)


def print_outer_rungs(region, rungs, conflicts, head, tied, decision, is_closed):
    """The outer rail was walked into the order the source band already used.

    ``rungs`` are the ``(inner, outer)`` column pairs the source faces joined with an
    edge, so ``conflicts`` counts how many of them the chosen ``(orientation, rotate)``
    would contradict and ``head`` breaks the ties that leaves.  ``tied=1`` means the
    source band's own connectivity settled the cut; more means distance still had to.
    """
    shown = ", ".join(f"{inner}->{outer}" for inner, outer in rungs[:8])
    if len(rungs) > 8:
        shown += f", ..{len(rungs) - 8} more"
    print(
        "[Loop Resample][diagnostic] align "
        f"region={region.get('region_index')} rungs=[{shown}] "
        f"conflicts={conflicts} head={head} tied={tied} "
        f"chosen={decision[0]} rotate={decision[1]} closed={int(is_closed)}"
    )


def print_outer_align(region, candidates, chosen_index, rotate, is_closed):
    """The two orientations' pairing costs, and which one the strip walked.

    For a closed rail ``rotate`` is the captured index the outer rail now starts at,
    so a step whose ``rotate`` moved has shifted every rung by that many columns -- a
    whole band's worth of connectivity change from one wheel tick.
    """
    print(
        "[Loop Resample][diagnostic] align "
        f"region={region.get('region_index')} closed={int(is_closed)} "
        "costs=["
        + ",".join(f"{cost:.6f}" for cost, _ in candidates)
        + f"] chosen={chosen_index} rotate={rotate}"
    )


def print_outer_replay(region, decision):
    """The outer rail was walked in the order the frozen ladder chose for it.

    Printed under the same ``align`` tag as a fresh choice, because the line disappearing
    from a scroll would otherwise read as "no alignment happened" rather than the truth:
    the two orientations were never re-measured, so a ``rotate`` that moved cannot be
    blamed on this step.
    """
    print(
        "[Loop Resample][diagnostic] align "
        f"region={region.get('region_index')} replay=chosen{decision[0]} "
        f"rotate={decision[1]}"
    )


def print_ladder_dp(region, inner_steps, outer_steps, allowed, ranked, waypoints):
    """The search's cheapest ladder and its closest rival among the last moves.

    ``runner`` is the best complete ladder that ended on a *different* final move, so
    ``gap`` is an upper bound on the margin the search really won by -- the true
    second-best ladder may share the winner's last step and never surface here.  On a
    two-transition strip every ladder has a different final move, so the bound is exact
    and ``gap`` is the whole margin a shape axis had to overcome to move the strip.
    """
    best_cost, best_transitions = ranked[0]
    line = (
        "[Loop Resample][diagnostic] ladder "
        f"region={region.get('region_index')} steps={inner_steps}x{outer_steps} "
        "allowed="
        + "/".join(_LADDER_KIND_LETTER.get(kind, "?") for kind in allowed)
        + f" finals={len(ranked)}"
        + " pins="
        + ("-" if not waypoints else str(sorted(set(waypoints))))
        + f" dp={_ladder_sequence(best_transitions)} score={best_cost:.6f}"
    )
    if len(ranked) > 1:
        line += (
            f" runner={_ladder_sequence(ranked[1][1])}"
            f" gap={ranked[1][0] - best_cost:.6f}"
        )
    else:
        line += " runner=- gap=inf"
    print(line)


def print_ladder_plan(region, plan, source, swapped):
    """The ladder that became faces, with the rung length of every one of its columns.

    ``source`` is how the strip came by that ladder: ``dp`` solved it, ``reuse`` replayed
    the frozen one, and ``reflow`` found the frozen one no longer fits its rails and
    solved again -- which is the one number that says how often a saved wiring outlives
    its own geometry.  ``swapped`` marks that the local pass rewrote what the search
    chose.  ``rungs`` is what ``_step_cost`` pays ``1.2 * length ** 2`` for: two
    neighbouring columns swapping which rung is the shorter one is the flip, and its
    threshold is where those two numbers are equal.
    """
    inner = plan.inner_vertices
    outer = plan.outer_vertices
    rungs = [
        (
            _point(outer[outer_index % len(outer)])
            - _point(inner[inner_index % len(inner)])
        ).length
        for inner_index, outer_index in plan.nodes
    ]
    print(
        "[Loop Resample][diagnostic] ladder-final "
        f"region={region.get('region_index')} wiring={source} "
        f"{'swapped' if swapped else 'kept'}="
        f"{_ladder_sequence(plan.transitions)} score={plan.score:.6f} "
        "nodes=["
        + ",".join(f"{i}>{o}" for i, o in plan.nodes)
        + "] rungs=["
        + ",".join(f"{length:.6f}" for length in rungs)
        + "]"
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
            doubled = len(knots) - len({value[0] for value in knots})
            print(
                f"[Loop Resample][uvdiag]     chain{index} knots={len(knots)} "
                f"u=[{knots[0][0]:.6f},{knots[-1][0]:.6f}] "
                f"closed={int(chain['closed'])}"
                + (f" doubled={doubled}" if doubled else "")
            )


def print_uv_note(region, detail):
    """A one-line UV fact that has no face to attach to."""
    print(f"[Loop Resample][uvdiag] {_region_tag(region)} {detail}")


def print_uv_faces(region, rows, total):
    """Every rebuilt face the UV transfer could not place cleanly.

    A line is emitted when a corner was clamped to a chain end, when a corner took the
    value its matched source face keeps on a doubled rail vertex instead of
    interpolating, when the face fell through to the nearest-centre guess, when several
    source faces tied for it, when it sits where a seam crosses, or when the island vote
    had to replace the face its overlap vote picked -- the ways a wrong island can win,
    and the last one is what keeps a wire off the map.
    """
    flagged = [
        row
        for row in rows
        if row["island_vote"]
        or row["fallback"]
        or row["tied"] > 1
        or row["near_seam"]
        or any(probe["clamped"] or probe.get("tied") for probe in row["probes"])
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
                + (" TIED" if probe.get("tied") else "")
                for probe in row["probes"]
            )
        )
