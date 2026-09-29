"""Say *how* two smoke dumps differ, which an md5 cannot.

``_smoke.py`` writes a dump and the habit has been to md5 the two files: same hash means
the change moved nothing.  That half is sound and it is the half that gets trusted, so the
other half matters -- a differing hash says only "something moved", and "something moved"
is not an answer when the question was whether a commit changed the topology or nudged a
handful of vertices.  Guessing from there is how a result-changing commit gets waved
through, and it is also how a harmless one gets reverted.

So this parses both dumps and reports, per section: whether face and edge counts held, how
many vertex positions moved and how far, whether the moved ones cluster or scatter, whether
the bounding box held, and whether UVs moved with the vertices or on their own.  UVs
differing by exactly the count the vertices did is the expected signature of a UV that is
carried; a different number means the UV layer was resampled independently.

Two honesty notes.  Nearest-neighbour over two point clouds is quadratic, so the moved
cloud is reduced to unique positions and sampled -- the worst-case distance therefore
understates, and the sample size is printed beside it.  The bounding box is the unsampled
global figure and is what to read first.

Lines within a section are sorted, so a moved vertex also moves its line and a plain text
diff pairs the wrong things.  Everything here compares multisets instead.

Run:  python tools/_dumpdiff.py <before.dump> <after.dump> [--moves N]
"""
import argparse
import re
import sys
from collections import Counter

FACE = re.compile(r"^F (\d+) m=(-?\d+) s=(-?\d+) \| (.*)$")
TUPLE = re.compile(r"\(([^)]*)\)")
# Nearest-neighbour query side.  Both clouds are deduped first, so this is unique
# positions, not vertex slots.
SAMPLE_CAP = 400


def parse(path):
    """Split a dump into ``{section: {"F": [...], "E": [...]}}``, order preserved."""
    sections = {}
    name = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line.startswith("### "):
                name = line[4:]
                sections[name] = {"F": [], "E": []}
            elif name and line[:1] in ("F", "E"):
                sections[name][line[0]].append(line)
    return sections


def face_records(lines):
    """Each face as (valence, material, smooth, [coords per loop], [uv per loop]).

    A loop contributes two parenthesised groups -- its coordinate and its UV -- so the
    even ones are positions.  A mesh with no active UV layer dumps ``()`` for the second,
    which parses to an empty tuple rather than a crash.
    """
    out = []
    for line in lines:
        match = FACE.match(line)
        if not match:
            continue
        valence, material, smooth, rest = match.groups()
        coords = []
        uvs = []
        for position, group in enumerate(TUPLE.findall(rest)):
            numbers = (
                () if not group.strip()
                else tuple(round(float(part), 9) for part in group.split(","))
            )
            (uvs if position % 2 else coords).append(numbers)
        out.append((int(valence), int(material), int(smooth), coords, uvs))
    return out


def positions(records):
    return Counter(coord for record in records for coord in record[3] if coord)


def uv_values(records):
    return Counter(uv for record in records for uv in record[4] if uv)


def box(points):
    """Extent of a point cloud, or None if there is nothing to measure."""
    if not points:
        return None
    lows = [min(point[axis] for point in points) for axis in range(3)]
    highs = [max(point[axis] for point in points) for axis in range(3)]
    return lows, highs


def format_box(measure):
    if measure is None:
        return "(empty)"
    lows, highs = measure
    return (f"({lows[0]:.5f}, {lows[1]:.5f}, {lows[2]:.5f}) .. "
            f"({highs[0]:.5f}, {highs[1]:.5f}, {highs[2]:.5f})")


def format_span(measure):
    lows, highs = measure
    return f"({highs[0] - lows[0]:.5f}, {highs[1] - lows[1]:.5f}, {highs[2] - lows[2]:.5f})"


def nearest(lost, gained):
    """Worst and mean distance from each moved-away position to its nearest arrival.

    Returns (worst, mean, sampled, unique) or None when one side is empty -- a section
    where faces appeared or vanished outright has no pairing to measure, and reporting a
    distance there would be inventing one.
    """
    unique_lost = sorted(set(lost))
    unique_gained = sorted(set(gained))
    if not unique_lost or not unique_gained:
        return None
    stride = max(1, len(unique_lost) // SAMPLE_CAP)
    sample = unique_lost[::stride][:SAMPLE_CAP]
    worst = 0.0
    total = 0.0
    for point in sample:
        best = min(
            sum((a - b) ** 2 for a, b in zip(point, other)) ** 0.5
            for other in unique_gained
        )
        worst = max(worst, best)
        total += best
    return worst, total / len(sample), len(sample), len(unique_lost)


def pairs_by_nearest(lost, gained):
    """Each moved-away position with the arrival closest to it, worst first."""
    unique_gained = sorted(set(gained))
    if not unique_gained:
        return []
    out = []
    for point in sorted(set(lost)):
        other = min(
            unique_gained,
            key=lambda candidate: sum((a - b) ** 2 for a, b in zip(point, candidate)),
        )
        distance = sum((a - b) ** 2 for a, b in zip(point, other)) ** 0.5
        out.append((distance, point, other))
    out.sort(reverse=True)
    return out


def compare(name, before, after, moves):
    """One section.  Returns True when it changed."""
    unchanged = before["F"] == after["F"] and before["E"] == after["E"]
    b_faces = face_records(before["F"])
    a_faces = face_records(after["F"])
    print(f"{name:<28} faces {len(b_faces):>6}->{len(a_faces):>6}  "
          f"edges {len(before['E']):>6}->{len(after['E']):>6}  "
          f"{'IDENTICAL' if unchanged else 'CHANGED'}")
    if unchanged:
        return False

    print(f"  --- {name}")
    b_points, a_points = positions(b_faces), positions(a_faces)
    lost = list((b_points - a_points).elements())
    gained = list((a_points - b_points).elements())
    shared = sum((b_points & a_points).values())
    print(f"    vertex slots   : {sum(b_points.values())} -> {sum(a_points.values())} "
          f"({shared} in both, {len(lost)} moved)")

    # Counts first: a topology change is a different conversation from a vertex nudge, and
    # valence/material/smooth are the parts of it a coordinate diff cannot see.
    b_valence = Counter(record[0] for record in b_faces)
    a_valence = Counter(record[0] for record in a_faces)
    if b_valence != a_valence:
        print(f"    face valence   : {dict(sorted(b_valence.items()))} -> "
              f"{dict(sorted(a_valence.items()))}   *** TOPOLOGY ***")
    b_flags = Counter((record[1], record[2]) for record in b_faces)
    a_flags = Counter((record[1], record[2]) for record in a_faces)
    if b_flags != a_flags:
        print(f"    material/smooth: {dict(b_flags)} -> {dict(a_flags)}")

    measure = nearest(lost, gained)
    if measure is None:
        print("    move distance  : not measurable -- one side has no positions "
              "(faces appeared or vanished outright)")
    else:
        print(f"    move distance  : worst {measure[0]:.6g}, mean {measure[1]:.6g} "
              f"(sampled {measure[2]} of {measure[3]} unique moved positions)")

    b_box, a_box = box(b_points), box(a_points)
    print(f"    bounding box   : {format_box(b_box)}")
    if b_box != a_box:
        print(f"                 -> {format_box(a_box)}   *** EXTENT MOVED ***")

    b_uv, a_uv = uv_values(b_faces), uv_values(a_faces)
    uv_moved = sum((b_uv - a_uv).values())
    print(f"    uv values      : {sum(b_uv.values())} -> {sum(a_uv.values())} "
          f"({uv_moved} differ"
          f"{'' if uv_moved == len(lost) else ' -- not equal to the vertex count'})")

    moved_box = box(set(lost))
    if moved_box is not None:
        print(f"    moved cluster  : {format_box(moved_box)}")
        print(f"      cluster span : {format_span(moved_box)}"
              f"   (whole model {format_span(b_box)})")

    if moves:
        print(f"    largest {moves} moves:")
        for distance, point, other in pairs_by_nearest(lost, gained)[:moves]:
            print(f"      ({point[0]:>10.6f},{point[1]:>10.6f},{point[2]:>10.6f}) -> "
                  f"({other[0]:>10.6f},{other[1]:>10.6f},{other[2]:>10.6f})"
                  f"   d={distance:.6f}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare two _smoke.py dumps and say what moved."
    )
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument(
        "--moves", type=int, default=0,
        help="list this many individual moves per changed section, largest first",
    )
    args = parser.parse_args(argv)

    before = parse(args.before)
    after = parse(args.after)
    print(f"sections: {len(before)} before, {len(after)} after")

    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    if only_before:
        print(f"only in before: {', '.join(only_before)}")
    if only_after:
        print(f"only in after : {', '.join(only_after)}")
    print()

    changed = 0
    for name in sorted(before):
        if name not in after:
            print(f"{name:<28} MISSING from the second dump")
            changed += 1
            continue
        if compare(name, before[name], after[name], args.moves):
            changed += 1

    print()
    print(f"{changed} of {len(before)} sections changed")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
