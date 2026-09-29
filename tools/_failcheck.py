"""Does a crash a user cannot name still arrive with the frame attached?

The notice is the only thing a user can screenshot, and the stripped tree no longer prints a
traceback, so ``_failure_location`` is the whole of what survives a failure this file did not
write.  This forces one and checks the sentence that comes back.

Run:  blender --background --factory-startup --python _failcheck.py -- <parent> <package>
"""
import importlib
import os
import sys

ARG = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(ARG) != 2:
    raise SystemExit(__doc__.strip().splitlines()[-1])
PARENT, PACKAGE = (value.replace("\\", "/") for value in ARG)
BLEND = os.path.join(os.environ["TEMP"], "hrprobe", "High_probe.blend").replace("\\", "/")

import bpy

bpy.ops.wm.open_mainfile(filepath=BLEND)

sys.path.insert(0, PARENT)
package = importlib.import_module(PACKAGE)
package.register()
sessions = importlib.import_module(f"{PACKAGE}.core.session")
operators = importlib.import_module(f"{PACKAGE}.operators")

target = None
for obj in bpy.context.view_layer.objects:
    if obj.type != "MESH" or not any(edge.select for edge in obj.data.edges):
        continue
    for other in bpy.context.view_layer.objects:
        other.select_set(other is obj)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        sessions.begin(bpy.context)
    except ValueError:
        bpy.ops.object.mode_set(mode="OBJECT")
        continue
    target = obj
    break

problems = []
if target is None:
    problems.append("nothing runnable in the archive")
else:
    session = sessions.active(bpy.context)
    counts = list(session.counts)

    def crash(*args, **kwargs):
        raise AttributeError("'NoneType' object has no attribute 'co'")

    real = operators._resample
    operators._resample = crash
    try:
        succeeded, message = operators.apply_counts(bpy.context, session, counts)
    finally:
        operators._resample = real

    print(f"[failcheck] succeeded={succeeded}")
    print(f"[failcheck] message={message}")
    if succeeded:
        problems.append("the forced crash did not come back as a refusal")
    if "_failcheck.py:" not in message:
        problems.append("the message carries no file:line")
    if message.count("(") != message.count(")"):
        problems.append("the message has unbalanced brackets")

    # A refusal this file wrote itself already says why, but it gets the frame too: telling
    # the two apart would mean knowing every exception the tree raises, and a location on a
    # notice the user can act on anyway costs nothing.
    def refuse(*args, **kwargs):
        raise ValueError("The selected edges cross each other.")

    operators._resample = refuse
    try:
        succeeded, message = operators.apply_counts(bpy.context, session, counts)
    finally:
        operators._resample = real
    print(f"[failcheck] refusal={message}")
    if "_failcheck.py:" not in message:
        problems.append("the refusal lost its frame, so the two kinds no longer differ")

    sessions.end()
    bpy.ops.object.mode_set(mode="OBJECT")

package.unregister()
for problem in problems:
    print("[failcheck] FAIL", problem)
print("[failcheck] PASS" if not problems else f"[failcheck] FAIL ({len(problems)})")
sys.exit(1 if problems else 0)
