"""Which archive objects actually reach the four lines the dead-local pass once unbound.

The bit-compare dump is only as good as the paths the model takes.  ``Low_2`` carries no
edge attributes, so it never enters the loops where ``projection_scans``, ``compared``,
``work`` and ``attempts`` were incremented -- and a stripped build that would have raised
UnboundLocalError on all four still matched the dev tree byte for byte.  This finds objects
that do reach them, so the smoke test can be pointed at one instead of hoping.

Run:  blender --background --factory-startup --python _cover.py -- <parent> <package> [attrs]
"""
import importlib
import os
import sys
import traceback

ARG = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(ARG) not in (2, 3):
    raise SystemExit(__doc__.strip().splitlines()[-1])
PARENT, PACKAGE = (value.replace("\\", "/") for value in ARG[:2])
# The archive's meshes arrive with no edge attributes, so the loops that carry them never
# turn.  Arming crease, bevel weight and sharpness is what makes them reachable at all.
ARM_ATTRIBUTES = "attrs" in ARG[2:]
# Objects above this are multi-hundred-thousand-face scans; tracing them costs more than the
# answer is worth, and the small ones carry the same code paths.
FACE_CAP = 20000
DELTAS = [0, 1, 2, -1, -2, 3]
BLEND = os.path.join(os.environ["TEMP"], "hrprobe", "High_probe.blend").replace("\\", "/")

import bpy

bpy.ops.wm.open_mainfile(filepath=BLEND)
sys.path.insert(0, PARENT)
package = importlib.import_module(PACKAGE)
sessions = importlib.import_module(f"{PACKAGE}.core.session")
operators = importlib.import_module(f"{PACKAGE}.operators")

# The four increments, as dev-tree line numbers, plus the file each sits in.
TARGETS = {
    "core/attributes.py": {250: "projection_scans", 304: "compared"},
    "core/surface.py": {929: "work"},
    "core/planner.py": {1845: "attempts"},
}

root = os.path.dirname(package.__file__).replace("\\", "/")
watched = {}
for relative, lines in TARGETS.items():
    path = f"{root}/{relative}"
    if not os.path.exists(path):
        raise SystemExit(f"no such file in the loaded tree: {path}")
    watched[os.path.realpath(path)] = lines

hit = {}
per_object = {}


def arm(mesh):
    """Crease and bevel weight are named attributes now, and crease_edge may already exist."""
    for name, value in (("crease_edge", 0.5), ("bevel_weight_edge", 0.3)):
        layer = mesh.attributes.get(name)
        if layer is None:
            layer = mesh.attributes.new(name=name, type="FLOAT", domain="EDGE")
        for item in layer.data:
            item.value = value
    for edge in mesh.edges:
        edge.use_edge_sharp = True
    mesh.update()


def tracer(frame, event, arg):
    if event == "call":
        path = os.path.realpath(frame.f_code.co_filename.replace("\\", "/"))
        return tracer if path in watched else None
    if event == "line":
        path = os.path.realpath(frame.f_code.co_filename.replace("\\", "/"))
        lines = watched.get(path)
        if lines and frame.f_lineno in lines:
            name = lines[frame.f_lineno]
            hit[name] = hit.get(name, 0) + 1
            per_object.setdefault(name, set()).add(current)
    return tracer


package.register()
current = "?"
sys.settrace(tracer)
try:
    for obj in bpy.context.view_layer.objects:
        if obj.type != "MESH" or not any(edge.select for edge in obj.data.edges):
            continue
        if len(obj.data.polygons) > FACE_CAP:
            continue
        current = obj.name
        for other in bpy.context.view_layer.objects:
            other.select_set(other is obj)
        bpy.context.view_layer.objects.active = obj
        if ARM_ATTRIBUTES:
            arm(obj.data)
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            sessions.begin(bpy.context)
        except Exception as exc:
            print(f"skip {obj.name}: {type(exc).__name__} {str(exc)[:60]}")
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
            continue
        session = sessions.active(bpy.context)
        entry = list(session.counts)
        for delta in DELTAS:
            counts = [value + delta for value in entry]
            if any(value < 3 for value in counts):
                continue
            try:
                operators.apply_counts(bpy.context, session, counts)
            except Exception:
                print(f"  !! {obj.name} delta={delta}: {traceback.format_exc(limit=3)}")
        try:
            operators.restore_source(bpy.context, session, entry)
        except Exception:
            pass
        sessions.end()
        bpy.ops.object.mode_set(mode="OBJECT")
finally:
    sys.settrace(None)
    current = "?"

print("\n=== coverage of the four increments ===")
for relative, lines in TARGETS.items():
    for line, name in lines.items():
        who = sorted(per_object.get(name, ()))
        print(f"{relative}:{line} {name:18} hits={hit.get(name, 0):<6} "
              f"objects={', '.join(who[:8]) if who else 'NONE'}")
package.unregister()
