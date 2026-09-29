"""Load a copy of the package, run real steps on real meshes, dump them, stay quiet.

Two jobs in one.  The first is structural: line surgery driven by an AST can produce a file
that parses and still falls over when it is imported, registered, or run, and only running
it finds that.  The second is the answer -- the dump is the whole edit mesh at full float
precision, so running this once against the dev tree and once against a stripped copy and
diffing the two dumps is a bit-compare on a real model rather than a synthetic one.

Coverage is the part that is easy to get wrong, and this file was widened after it went
wrong.  It used to run the first object the archive offered and report a byte-identical
dump; that object carries no edge attributes, so the loops incrementing ``projection_scans``,
``compared``, ``work`` and ``attempts`` never turned, and a build that would have raised
UnboundLocalError in all four still matched.  A dump only compares the paths the model
takes.  So this now walks every object small enough to be worth tracing, steps the counts
down as well as up because a dropped count is what leaves more records than rungs, dumps
edges and not just faces because half the attributes carried live on an edge, and can arm
the edge attributes a mesh that arrived with none would never exercise.

Prints are intercepted while the package works, so a single stray line is a failure.

Run:  blender --background --factory-startup --python _smoke.py -- <parent> <package> <dump> [loud] [attrs] [synth]
"""
import builtins
import importlib
import io
import os
import sys
import traceback

ARG = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not 3 <= len(ARG) <= 5:
    raise SystemExit(__doc__.strip().splitlines()[-1])
PARENT, PACKAGE, DUMP = (value.replace("\\", "/") for value in ARG[:3])
FLAGS = set(ARG[3:])
if FLAGS - {"loud", "attrs", "synth"}:
    raise SystemExit(f"unknown flag(s): {', '.join(sorted(FLAGS - {'loud', 'attrs', 'synth'}))}")
# The dev tree is the baseline for the diff, and it ships with the diagnostics on, so it is
# *supposed* to talk.  A stripped copy is not, and for that one ``loud`` is left out.
QUIET_REQUIRED = "loud" not in FLAGS
# Crease and bevel weight on every edge, so the attribute carry-over runs on a mesh that
# arrived with none.  Seam is deliberately left alone: a seam anchors a rung, so arming one
# would move the solve and the two trees would no longer be answering the same question.
ARM_ATTRIBUTES = "attrs" in FLAGS
# The archive was saved by 5.2 and Blender will not open a file from a newer version, so an
# older build cannot read it at all.  ``synth`` builds an open tube with its two rim loops
# selected instead -- a band the planner accepts -- which trades his geometry for something
# every version can make.  What that still proves is the part 4.2 compatibility is about:
# the package imports, registers, runs a step and unregisters without touching an API this
# version does not have.  It is not a substitute for the bit-compare on his model.
SYNTH = "synth" in FLAGS
DELTAS = [0, 1, 2, 3, 4, -1, -2]
# Above this the archive holds half-a-million-face scans whose dumps dwarf the answer.
FACE_CAP = 20000
BLEND = os.path.join(os.environ["TEMP"], "hrprobe", "High_probe.blend").replace("\\", "/")

import bpy
import bmesh

if not SYNTH:
    bpy.ops.wm.open_mainfile(filepath=BLEND)

sys.path.insert(0, PARENT)
package = importlib.import_module(PACKAGE)

real_print = builtins.print
captured = io.StringIO()


def intercepted(*values, **kwargs):
    kwargs["file"] = captured
    real_print(*values, **kwargs)


def say(*values):
    real_print(*values)


def guard(label, problems, body):
    """Run ``body`` with the package's print() pointed at a buffer instead of the console."""
    builtins.print = intercepted
    try:
        body()
    except BaseException as exc:  # noqa: BLE001 - the point is to report it, not raise
        problems.append(f"{label} raised {exc!r}")
        say(traceback.format_exc().rstrip())
    finally:
        builtins.print = real_print


say(f"[smoke] loaded {package.__file__}")
loaded_from = os.path.dirname(os.path.abspath(package.__file__))
if not os.path.samefile(loaded_from, os.path.join(PARENT, PACKAGE)):
    say(f"[smoke] FAIL imported {loaded_from}, not the copy that was asked for")
    sys.exit(1)

sessions = importlib.import_module(f"{PACKAGE}.core.session")
operators = importlib.import_module(f"{PACKAGE}.operators")

problems = []
guard("register()", problems, package.register)

dumps = {}
layers_seen = 0
dumps_expected = 0


def point(vertex):
    return tuple(round(value, 12) for value in vertex.co)


def dump(target):
    """The whole edit mesh, sorted and keyed by coordinate so a renumbering hides nothing."""
    global layers_seen
    bm = bmesh.from_edit_mesh(target.data)
    layer = bm.loops.layers.uv.active
    layers_seen += 1 if layer is not None else 0
    floats = tuple(bm.edges.layers.float)
    lines = []
    for face in bm.faces:
        lines.append(
            "F %d m=%d s=%d | %s"
            % (
                len(face.verts),
                face.material_index,
                int(face.smooth),
                " ".join(
                    "%s|%s"
                    % (
                        point(loop.vert),
                        tuple(round(value, 12) for value in loop[layer].uv)
                        if layer is not None
                        else (),
                    )
                    for loop in face.loops
                ),
            )
        )
    for edge in bm.edges:
        first, second = sorted(point(vertex) for vertex in edge.verts)
        lines.append(
            "E %s %s sel=%d seam=%d smooth=%d%s"
            % (
                first,
                second,
                int(edge.select),
                int(edge.seam),
                int(edge.smooth),
                "".join(
                    " %s=%s" % (each.name, round(edge[each], 12)) for each in floats
                ),
            )
        )
    lines.sort()
    return lines


def arm(mesh):
    """Give every edge something to carry, on a mesh that arrived with nothing.

    Crease and bevel weight are named attributes now, not fields on ``MeshEdge``, and
    ``crease_edge`` already exists on a mesh that has ever been through the sculpt or
    subdivision tools -- so this looks before it creates.  Creating blind adds a second
    ``crease_edge.001``, and the bmesh float layer for it is then reported to the dump
    under a name the package never asked for.
    """
    for name, value in (("crease_edge", 0.5), ("bevel_weight_edge", 0.3)):
        layer = mesh.attributes.get(name)
        if layer is None:
            layer = mesh.attributes.new(name=name, type="FLOAT", domain="EDGE")
        for item in layer.data:
            item.value = value
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    mesh.update()


def run_object(obj):
    """Every delta on one object.  True when the planner accepted it at least once."""
    global dumps_expected
    for other in bpy.context.view_layer.objects:
        other.select_set(other is obj)
    bpy.context.view_layer.objects.active = obj
    if ARM_ATTRIBUTES:
        arm(obj.data)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        sessions.begin(bpy.context)
    except ValueError as exc:
        say(f"[smoke] skipped {obj.name}: {str(exc)[:70]}")
        bpy.ops.object.mode_set(mode="OBJECT")
        return False
    session = sessions.active(bpy.context)
    entry_counts = list(session.counts)
    say(f"[smoke] {obj.name} entry_counts={entry_counts}")
    try:
        for delta in DELTAS:
            counts = [entry + delta for entry in entry_counts]
            if any(count < 3 for count in counts):
                continue
            succeeded, message = operators.apply_counts(bpy.context, session, counts)
            if not succeeded:
                # An exception the operator caught reads as a refusal, so the prefix is what
                # tells a crash apart from the planner saying no.  Only the first is a
                # failure; the second is an answer, and the dump diff polices it.
                if message.startswith(operators.FAILURE_PREFIX):
                    problems.append(f"{obj.name} delta={delta} crashed: {message}")
                say(f"[smoke] {obj.name} delta={delta} refused: {message}")
                continue
            dumps[(obj.name, delta)] = dump(obj)
            dumps_expected += 1
            say(f"[smoke] {obj.name} delta={delta} lines={len(dumps[(obj.name, delta)])}")
        guard(
            f"restore_source on {obj.name}",
            problems,
            lambda: operators.restore_source(bpy.context, session, entry_counts),
        )
    finally:
        sessions.end()
        bpy.ops.object.mode_set(mode="OBJECT")
    return bool(dumps_expected)


def synth():
    """An open tube with both rim loops selected: a band two rails and nothing else.

    The primitive arrives fully selected, and in the default vertex select mode that comes
    back as every edge selected once the mesh has been through object mode -- which reads as
    a vertex of degree four, i.e. the planner's "the selected edges cross each other".  So
    this clears the selection before making one, and selects the rim vertices with the rim
    edges because a vertex select mode derives edges from them.
    """
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.0, depth=2.0)
    obj = bpy.context.active_object
    bpy.context.tool_settings.mesh_select_mode = (False, True, False)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    # The caps would give the region somewhere to go that is not between the two rails.
    caps = [face for face in bm.faces if abs(face.calc_center_median().z) > 0.9]
    bmesh.ops.delete(bm, geom=caps, context="FACES")
    bm.edges.ensure_lookup_table()
    for edge in bm.edges:
        heights = [vertex.co.z for vertex in edge.verts]
        edge.select = all(value > 0.9 for value in heights) or all(
            value < -0.9 for value in heights
        )
    for vertex in bm.verts:
        vertex.select = any(edge.select for edge in vertex.link_edges)
    bm.select_flush(False)
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    say(f"[smoke] synth {obj.name}: {len(obj.data.polygons)} faces, "
        f"{sum(1 for edge in obj.data.edges if edge.select)} selected edges")
    return obj


candidates = (
    [synth()]
    if SYNTH
    else [
        obj
        for obj in bpy.context.view_layer.objects
        if obj.type == "MESH"
        and len(obj.data.polygons) <= FACE_CAP
        and any(edge.select for edge in obj.data.edges)
    ]
)
say(f"[smoke] {len(candidates)} candidate objects")
for obj in candidates:
    guard(obj.name, problems, lambda obj=obj: run_object(obj))
if not dumps:
    problems.append("nothing runnable in the archive")
elif layers_seen != dumps_expected:
    problems.append("no active uv layer, so the uv half of the dump compares nothing")

guard("unregister()", problems, package.unregister)


def cycle():
    package.register()
    package.unregister()


guard("a second register/unregister pair", problems, cycle)

said = captured.getvalue().splitlines()
if QUIET_REQUIRED:
    for line in said:
        if line.strip():
            problems.append(f"the package printed: {line.strip()[:100]}")
else:
    say(f"[smoke] the package printed {sum(1 for line in said if line.strip())} lines")

if DUMP and dumps and not problems:
    with open(DUMP, "w", encoding="utf-8", newline="\n") as handle:
        for key in sorted(dumps):
            handle.write(f"### {key[0]} delta={key[1]}\n")
            handle.write("\n".join(dumps[key]) + "\n")
    say(f"[smoke] wrote {DUMP}: {len(dumps)} dumps, "
        f"{sum(len(value) for value in dumps.values())} lines")

for problem in problems:
    say("[smoke] FAIL", problem)
say("[smoke] PASS" if not problems else f"[smoke] FAIL ({len(problems)} problems)")
sys.exit(1 if problems else 0)
