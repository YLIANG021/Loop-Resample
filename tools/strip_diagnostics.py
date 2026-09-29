"""Turn the working tree into the tree that ships: take the diagnostics layer out.

The working tree keeps the diagnostics so a bug can still be chased down; the package that
goes to the platform may not carry a printing module that never runs.  This is the step
between the two, so a release is one command rather than a thousand lines deleted by hand.

Run from the repository root::

    python tools/strip_diagnostics.py --check      # report, write nothing
    python tools/strip_diagnostics.py              # rewrite the tree in place

It only ever acts on shapes it recognises, and it stops on anything else: a diagnostic gate
with an ``else`` behind it, an assignment it cannot prove side-effect-free, a file that no
longer parses, a ``print(`` left standing.  A release build that guessed would be worse than
no release build.

What comes out, in order:

1. ``core/diagnostics.py``, and every ``from ... diagnostics import ...`` line.
2. Every ``if`` gated on ``enabled()`` / ``DIAGNOSTICS`` / ``DIAGNOSE_*``, whole block,
   together with the comment lines sitting directly on top of it -- a comment explaining a
   deleted block is a leftover all on its own.
3. Every bare call to a diagnostics function, plus the three functions outside that module
   which exist only to feed one (``print_capture_reject``, ``_step_request``,
   ``_region_scope``).
4. The ``x = <diag value> if DIAGNOSE_UV else None`` ternaries, collapsed to their ``else``
   branch: those assign a name live code may still read, so they are rewritten, not deleted.
5. Whatever 2 to 4 orphaned -- unread locals, unimported names, private helpers nothing
   calls any more.  Only an assignment whose right-hand side is provably side-effect-free is
   dropped, so a call that writes to the mesh can never be deleted for looking unused.

It does not touch a ``pgettext`` source string, a ``bl_description``, a ``bl_label``, or any
line of geometry.  The evidence that it worked is the smoke test and the bit-for-bit mesh
compare, not this script's own opinion.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys


GATE_TOKENS = ("enabled()", "DIAGNOSTICS", "DIAGNOSE_LADDER", "DIAGNOSE_UV")

# Functions that exist only to hand one diagnostic line its contents.  They live outside
# core/diagnostics.py, so they are named here rather than discovered from it.
EXTRA_DIAGNOSTIC_DEFS = ("print_capture_reject", "_step_request", "_region_scope")

# Calls safe to drop along with the name they assign.  Nothing here writes to the mesh, to a
# file, or to any state this script cannot see; anything not listed keeps its assignment.
PURE_BUILTINS = frozenset({
    "len", "sorted", "min", "max", "sum", "set", "list", "tuple", "frozenset", "dict",
    "str", "int", "float", "bool", "abs", "round", "enumerate", "zip", "any", "all",
    "isinstance", "range", "reversed", "repr", "format",
})
PURE_METHODS = frozenset({
    "get", "keys", "values", "items", "index", "count", "copy", "perf_counter",
})

MAX_ROUNDS = 12

# Edits too small or too prose-shaped for a rule, listed here instead: a plain substring
# swap that must match exactly ``count`` times or the whole run is refused.  A table this
# explicit is the point -- a release build should not have to guess at a sentence.  These
# run last, after the orphan rounds have settled, so nothing mops up behind them: each one
# has to take the whole of what it makes dead.  ``_unbound_augments`` is what says so.
#
# ``quiet`` exists only to hold the diagnostics down while a session captures its source, so
# once they are gone nothing reads it.  ``probe`` is the same shape one level down: the UV
# layer filled a dict or a list that only its own dump read, and the gate that decided
# between ``{}`` and ``None`` collapsed to ``None``, so every ``if probe is not None`` below
# it is a branch the package can no longer take.  Both are counters and out-parameters whose
# only reader left with the layer, and a parameter no caller fills is exactly the kind of
# leftover the strip is supposed to leave behind.
EXPLICIT_PATCHES: tuple[tuple[str, str, str, int], ...] = (
    (
        "core/regions.py",
        "def capture_adjacent_strips(bm, paths, quiet=False):",
        "def capture_adjacent_strips(bm, paths):",
        1,
    ),
    (
        "core/session.py",
        "capture_adjacent_strips(live_bm, paths, quiet=True)",
        "capture_adjacent_strips(live_bm, paths)",
        1,
    ),
    (
        "core/session.py",
        "live_bm, _apply_trims(paths, trims), quiet=True",
        "live_bm, _apply_trims(paths, trims)",
        1,
    ),
    # The sentence below describes a parameter the patch above just took out.
    (
        "core/regions.py",
        "    piece.  ``quiet`` holds the diagnostics back for that first, throwaway pass.\n",
        "    piece.\n",
        1,
    ),
    (
        "core/types.py",
        "# Columns one ladder step consumes of each rail.  The search, the validator and the\n"
        "# diagnostics all read this instead of restating the arithmetic.\n",
        "# Columns one ladder step consumes of each rail.  The search and the validator both\n"
        "# read this instead of restating the arithmetic.\n",
        1,
    ),
    # Returned and unpacked, read by nothing once the ladder dump is gone.  The name still
    # deserves a gloss; naming the layer that used to read it does not.
    (
        "core/planner.py",
        "    scrolled.  ``swapped`` is diagnostic only.\n",
        "    scrolled.  ``swapped`` says whether the local swap moved anything.\n",
        1,
    ),
    (
        "core/surface.py",
        "        vote = None\n"
        "        record = _match_face(records, start, end, closed, vote, outer_span)\n",
        "        record = _match_face(records, start, end, closed, outer_span)\n",
        1,
    ),
    (
        "core/surface.py",
        '        probes = None\n'
        "        for loop, rail, u, corner_index in corners:\n",
        "        for loop, rail, u, corner_index in corners:\n",
        1,
    ),
    (
        "core/surface.py",
        "                    rails[rail][chain_index], position, periodic, probes, corner_us[rail]\n",
        "                    rails[rail][chain_index], position, periodic, corner_us[rail]\n",
        1,
    ),
    (
        "core/surface.py",
        "def _match_face(records, start, end, closed, probe=None, outer=None):",
        "def _match_face(records, start, end, closed, outer=None):",
        1,
    ),
    (
        "core/surface.py",
        "    every time.\n"
        "\n"
        "    ``probe`` is the UV diagnostic's dict, read by nothing else: it learns\n"
        "    whether the vote was won outright, how many source faces tied for it, and\n"
        "    which rule settled it.\n"
        '    """\n',
        "    every time.\n"
        '    """\n',
        1,
    ),
    # ``positive`` and ``resolved`` exist to fill the dict the last patch in this group
    # takes away, so they go with it -- including the increment, which is the one write
    # ``_dead_locals`` would have had to reach for on its own.
    (
        "core/surface.py",
        "    runner_overlap = 0.0\n"
        "    positive = 0\n"
        "    for record in records:\n",
        "    runner_overlap = 0.0\n"
        "    for record in records:\n",
        1,
    ),
    (
        "core/surface.py",
        "            runner_overlap = overlap\n"
        "        if overlap > 0.0:\n"
        "            positive += 1\n"
        "    fallback = best is None\n"
        '    resolved = "inner"\n',
        "            runner_overlap = overlap\n"
        "    fallback = best is None\n",
        1,
    ),
    (
        "core/surface.py",
        "        resolved = (\n"
        '            "outer"\n'
        "            if ranked[0][0] < 0.0 and (len(ranked) < 2 or ranked[1][0] > ranked[0][0])\n"
        '            else "centre"\n'
        "        )\n"
        "        best = ranked[0][3]\n"
        "    if probe is not None:\n"
        '        probe["overlap"] = best_overlap\n'
        '        probe["tied"] = max(0, positive - 1)\n'
        '        probe["fallback"] = fallback\n'
        '        probe["resolved"] = resolved\n'
        "    return best\n",
        "        best = ranked[0][3]\n"
        "    return best\n",
        1,
    ),
    (
        "core/surface.py",
        "def _sample_chain(chain, u, periodic, probe=None, rail_us=()):\n"
        '    """Interpolate one island\'s rail polyline at u, as {layer name: Vector}.\n'
        "\n"
        "    ``probe`` is the UV diagnostic's list, read by nothing else: one entry per\n"
        "    sample giving the u asked for, the u window the chain covers, and whether\n"
        "    the answer had to be clamped to an end knot.  ``rail_us`` are the face's\n"
        "    other corners on this rail: a cut column has two copies and they say which\n"
        "    one this face stands on.\n"
        '    """\n',
        "def _sample_chain(chain, u, periodic, rail_us=()):\n"
        '    """Interpolate one island\'s rail polyline at u, as {layer name: Vector}.\n'
        "\n"
        "    ``rail_us`` are the face's other corners on this rail: a cut column has two\n"
        "    copies and they say which one this face stands on.\n"
        '    """\n',
        1,
    ),
    (
        "core/surface.py",
        "    if len(knots) == 1:\n"
        "        if probe is not None:\n"
        "            probe.append(\n"
        "                {\n"
        '                    "u": u,\n'
        '                    "low": knots[0][0],\n'
        '                    "high": knots[0][0],\n'
        '                    "clamped": abs(u - knots[0][0]) > 1e-9,\n'
        '                    "side": 0,\n'
        "                }\n"
        "            )\n"
        "        return knots[0][1]\n",
        "    if len(knots) == 1:\n"
        "        return knots[0][1]\n",
        1,
    ),
    (
        "core/surface.py",
        "    side = 0\n"
        "    asked = u\n",
        "    side = 0\n",
        1,
    ),
    (
        "core/surface.py",
        "    if probe is not None:\n"
        "        probe.append(\n"
        "            {\n"
        '                "u": asked,\n'
        '                "low": points[0][0],\n'
        '                "high": points[-1][0],\n'
        '                "clamped": factor < 0.0 or factor > 1.0,\n'
        '                "side": side,\n'
        "            }\n"
        "        )\n"
        "    factor = max(0.0, min(1.0, factor))\n",
        "    factor = max(0.0, min(1.0, factor))\n",
        1,
    ),
)


class Refusal(RuntimeError):
    """A shape this script will not guess at."""


def package_files(root: pathlib.Path):
    for path in sorted(root.rglob("*.py")):
        parts = set(path.relative_to(root).parts)
        if "tools" in parts or "__pycache__" in parts:
            continue
        yield path


def _diag_names(root: pathlib.Path) -> set[str]:
    module = root / "core" / "diagnostics.py"
    names = set()
    if module.exists():
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    return names | set(EXTRA_DIAGNOSTIC_DEFS)


def _mentions_gate(node: ast.AST) -> bool:
    text = ast.unparse(node)
    return any(token in text for token in GATE_TOKENS)


def _ends_with_diagnostics(node: ast.ImportFrom) -> bool:
    return bool(node.module) and node.module.split(".")[-1] == "diagnostics"


def _is_pure(node: ast.expr) -> bool:
    """Whether dropping this expression could change what the program does."""
    for child in ast.walk(node):
        if isinstance(child, (ast.Yield, ast.YieldFrom, ast.Await, ast.Lambda)):
            return False
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                if func.id not in PURE_BUILTINS:
                    return False
            elif isinstance(func, ast.Attribute):
                if func.attr not in PURE_METHODS:
                    return False
            else:
                return False
    return True


def _comment_run_above(lines: list[str], start: int) -> int:
    """The first line of the comment block sitting directly on top of ``start``.

    Only an unbroken run counts: a blank line in between means the comment was written
    about something else and stays where it is.
    """
    index = start - 1
    while index >= 0 and lines[index].strip().startswith("#"):
        index -= 1
    return index + 1


def _dedupe(edits: list[dict]) -> list[dict]:
    """Drop edits whose span sits inside another edit's span.

    ``ast.walk`` reports a nested call and the gated block around it as two edits; applying
    both would delete the same lines twice and eat whatever follows.
    """
    kept: list[dict] = []
    for edit in sorted(edits, key=lambda item: (item["start"], -item["end"])):
        if any(
            item["start"] <= edit["start"] and edit["end"] <= item["end"]
            for item in kept
        ):
            continue
        kept.append(edit)
    return kept


def _collect(tree: ast.Module, diag: set[str]) -> list[dict]:
    """Every edit one file needs, as line spans, before any of them is applied."""
    edits: list[dict] = []

    def drop(node: ast.AST, kind: str, note: str = "") -> None:
        edits.append({
            "kind": kind,
            "note": note,
            "start": node.lineno,
            "end": node.end_lineno,
            "text": None,
        })

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and _ends_with_diagnostics(node):
            drop(node, "import")
        elif isinstance(node, ast.If) and _mentions_gate(node.test):
            if node.orelse:
                raise Refusal(
                    f"line {node.lineno}: a diagnostic gate with an else/elif behind it "
                    f"-- {ast.unparse(node.test)[:60]}"
                )
            drop(node, "gate", ast.unparse(node.test)[:60])
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.IfExp):
            if _mentions_gate(node.value.test):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise Refusal(f"line {node.lineno}: a gated ternary with odd targets")
                edits.append({
                    "kind": "ternary",
                    "note": node.targets[0].id,
                    "start": node.lineno,
                    "end": node.end_lineno,
                    "text": None,
                    "value": ast.unparse(node.value.orelse),
                })
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id in diag:
                drop(node, "call", func.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in EXTRA_DIAGNOSTIC_DEFS:
                drop(node, "def", node.name)

    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("DIAGNOSE_LADDER", "DIAGNOSE_UV")
        ):
            drop(node, "constant", node.targets[0].id)

    edits = _settle_deletions(tree, edits)
    return edits


# A compound statement whose body was entirely diagnostics existed only to run them, so it
# goes too -- ``if alignment <= WARNING: print_normal_mismatch(...)`` is not an ``if`` the
# program still needs.  A body with an ``else`` behind it is refused instead of cascaded:
# dropping that would move control flow rather than remove reporting.
_CASCADE = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)
_HOLD = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _chain_covered(node: ast.If, covered) -> bool:
    """Whether an if/elif/else chain is diagnostic all the way down.

    ``if loan: print_a(...) elif loan_dropped: print_b(...)`` is one statement whose every
    branch only reports, so the whole chain goes.  A chain with live work in any branch does
    not: turning ``if X: report() else: work()`` into ``if not X: work()`` is a rewrite a
    build script has no business inventing.
    """
    while True:
        if not all(covered(item) for item in node.body):
            return False
        if not node.orelse:
            return True
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
            continue
        return all(covered(item) for item in node.orelse)


def _settle_deletions(tree: ast.Module, edits: list[dict]) -> list[dict]:
    """Delete upward until nothing is left empty, then guard what must stay."""
    guards: list[dict] = []
    guarded: set[int] = set()
    while True:
        spans = {
            (edit["start"], edit["end"])
            for edit in edits
            if edit["kind"] not in ("ternary", "pass")
        }

        def covered(node: ast.AST) -> bool:
            return any(
                start <= node.lineno and node.end_lineno <= end for start, end in spans
            )

        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, _CASCADE + _HOLD) or covered(node) or not node.body:
                continue
            if not all(covered(item) for item in node.body):
                continue
            if isinstance(node, _HOLD):
                if id(node) in guarded:
                    continue
                guarded.add(id(node))
                last = node.body[-1]
                guards.append({
                    "kind": "pass",
                    "note": node.name,
                    "start": last.end_lineno,
                    "end": last.end_lineno,
                    "text": None,
                    "insert": f"{' ' * node.body[0].col_offset}pass\n",
                })
                continue
            if isinstance(node, ast.If):
                if not _chain_covered(node, covered):
                    raise Refusal(
                        f"line {node.lineno}: this body is all diagnostics but a branch "
                        "behind it is not"
                    )
            elif getattr(node, "orelse", None):
                raise Refusal(
                    f"line {node.lineno}: emptying this body would drop an else clause"
                )
            edits.append({
                "kind": "cascade",
                "note": type(node).__name__,
                "start": node.lineno,
                "end": node.end_lineno,
                "text": None,
            })
            grew = True
        if not grew:
            break
    return _dedupe(edits) + guards


def _apply(lines: list[str], edits: list[dict], notes: list[str]) -> list[str]:
    """Rewrite one file's lines from the bottom up, so earlier spans stay valid.

    A comment block goes when any of its lines names the layer being removed; every block
    that decision touches is written into ``notes``, dropped and kept alike.  Position
    cannot answer this -- the prose above ``mark("plan")`` was written about the solve below
    it -- so the tool keeps its hands off anything the layer is not named in, and asks a
    person to read about the rest.
    """
    out = list(lines)
    for edit in sorted(edits, key=lambda item: (item["start"], item["end"]), reverse=True):
        if edit["kind"] == "pass":
            out.insert(edit["start"], _with_ending(edit["insert"], out[edit["start"] - 1]))
            continue
        start, end = edit["start"] - 1, edit["end"]
        if edit["kind"] == "ternary":
            indent = re.match(r"\s*", out[start]).group(0)
            out[start:end] = [
                _with_ending(f"{indent}{edit['note']} = {edit['value']}\n", out[start])
            ]
            continue
        if edit.get("text") is not None:
            out[start:end] = [_with_ending(edit["text"], out[start])]
            continue
        above = _comment_run_above(out, start)
        if above < start:
            if _about_diagnostics(out[above:start]):
                notes.append(f"{above + 1} dropped: {out[above].strip()[:72]}")
                start = above
            else:
                notes.append(f"{above + 1} kept: {out[above].strip()[:72]}")
        del out[start:end]
    return out


_ABOUT_DIAGNOSTICS = re.compile(
    r"\bdiagnostics?\b|\bDIAGNOSTICS\b|\bDIAGNOSE_\w+\b|\benabled\(\)"
)


def _about_diagnostics(run: list[str]) -> bool:
    return any(_ABOUT_DIAGNOSTICS.search(line) for line in run)


def _with_ending(text: str, sample: str) -> str:
    ending = "\r\n" if sample.endswith("\r\n") else "\n"
    return text.rstrip("\r\n") + ending


def _exported_names(tree: ast.Module) -> set[str]:
    """What ``__all__`` promises, since those names are referenced only by a string."""
    exported: set[str] = set()
    for node in ast.walk(tree):
        targets = getattr(node, "targets", ())
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in targets
        ):
            continue
        for element in getattr(node.value, "elts", ()):
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                exported.add(element.value)
    return exported


def _loaded_names(tree: ast.Module, imports: bool = True) -> set[str]:
    """Every name this file leans on.

    ``imports`` also counts what the import statements themselves bind, which is what keeps
    a private def alive when the only caller lives in another module.  Pruning imports needs
    the opposite answer -- a name the file merely imports is not a name the file uses -- so
    that one pass asks with ``imports=False``.
    """
    used = _exported_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
    if not imports:
        return used
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            used.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            used.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return used


def _dead_locals(tree: ast.Module) -> list[dict]:
    """Writes inside a function whose name nothing in that function ever reads.

    An increment counts as a write and not as the read it also is.  ``scans += len(points)``
    keeps a counter no surviving line asks for, and because ``ast`` spells its target with a
    Store context a load-only liveness test reads the counter as unread -- so it drops the
    ``scans = 0`` above and leaves the increment bound to nothing.  That is not a style
    problem: it is an UnboundLocalError on whichever path reaches the increment, and a path
    no test happens to take is still broken.  So a dead name takes every write to it, and a
    name this cannot prove inert keeps all of them.
    """
    edits = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        loads = {
            node.id
            for node in ast.walk(func)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        loads |= {
            node.value.id
            for node in ast.walk(func)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        }
        scoped = {
            name
            for node in ast.walk(func)
            if isinstance(node, (ast.Global, ast.Nonlocal))
            for name in node.names
        }
        writes: list[tuple[ast.stmt, set[str], bool]] = []
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                targets = [target for target in node.targets if isinstance(target, ast.Name)]
                if len(targets) != len(node.targets) or not targets:
                    continue
                writes.append((node, {target.id for target in targets}, _is_pure(node.value)))
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                writes.append((node, {node.target.id}, _is_pure(node.value)))

        unread = {
            name
            for _, names, _ in writes
            for name in names
            if name not in scoped and name not in loads
        }
        # One statement per name is not enough: ``x = f()`` this will not drop has to keep
        # the ``x = 0`` beside it, or dropping that one is what unbinds the increment.
        unprovable = {name for _, names, inert in writes if not inert for name in names}
        for node, names, _ in writes:
            if not names or not names <= unread or names & unprovable:
                continue
            edits.append({
                "kind": "dead-local",
                "note": ",".join(sorted(names)),
                "start": node.lineno,
                "end": node.end_lineno,
                "text": None,
            })
    return edits


def _bound_names(func: ast.AST) -> set[str]:
    """Every name a function body can hold a value in, before any of it runs."""
    arguments = func.args
    bound = {
        argument.arg
        for argument in (
            arguments.posonlyargs + arguments.args + arguments.kwonlyargs
        )
    }
    bound |= {arguments.vararg.arg} if arguments.vararg else set()
    bound |= {arguments.kwarg.arg} if arguments.kwarg else set()
    for node in ast.walk(func):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.Assign):
            bound.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            bound.update(
                part.id for part in ast.walk(node.target) if isinstance(part, ast.Name)
            )
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is None:
                    continue
                bound.update(
                    part.id
                    for part in ast.walk(item.optional_vars)
                    if isinstance(part, ast.Name)
                )
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
    return bound


def _unbound_augments(tree: ast.Module) -> list[str]:
    """Increments whose name the function never binds -- each one an UnboundLocalError.

    Liveness above is what could create these, so this is the check that says the reasoning
    held.  It is static on purpose: the four it was written for sat on paths a real model
    ran straight past, so a dump that matched the dev tree bit for bit certified a build
    that would still fall over in use.
    """
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = _bound_names(func)
        for node in ast.walk(func):
            if (
                isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id not in bound
            ):
                found.append(
                    f"line {node.lineno}: {func.name}() increments '{node.target.id}', "
                    "which nothing in it ever binds"
                )
    return found


def _dead_private_defs(tree: ast.Module, used: set[str]) -> list[dict]:
    edits = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_") or node.name in used or node.decorator_list:
            continue
        edits.append({
            "kind": "dead-def",
            "note": node.name,
            "start": node.lineno,
            "end": node.end_lineno,
            "text": None,
        })
    return edits


def _import_edits(tree: ast.Module, used: set[str]) -> list[dict]:
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dead = [
                alias for alias in node.names
                if (alias.asname or alias.name).split(".")[0] not in used
            ]
            if dead:
                edits.append({
                    "kind": "dead-import",
                    "note": ",".join(alias.name for alias in dead),
                    "start": node.lineno,
                    "end": node.end_lineno,
                    "text": None,
                })
        elif isinstance(node, ast.ImportFrom) and not _ends_with_diagnostics(node):
            dead = [
                alias for alias in node.names if (alias.asname or alias.name) not in used
            ]
            if not dead:
                continue
            if len(dead) == len(node.names):
                edits.append({
                    "kind": "dead-import",
                    "note": node.module or "",
                    "start": node.lineno,
                    "end": node.end_lineno,
                    "text": None,
                })
                continue
            keep = [alias for alias in node.names if alias not in dead]
            names = ", ".join(
                alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
                for alias in keep
            )
            # ``node.module`` never carries the leading dots, so a relative import has to
            # put them back or the rewritten line resolves against sys.path instead.
            origin = "." * node.level + (node.module or "")
            edits.append({
                "kind": "trim-import",
                "note": ",".join(alias.name for alias in dead),
                "start": node.lineno,
                "end": node.end_lineno,
                "text": f"{' ' * node.col_offset}from {origin} import {names}\n",
            })
    return edits


def _module_paths(tree: ast.Module) -> set[str]:
    """Every module a file imports, leading dots included.

    A trimmed import is rewritten as text, and text that loses its dots still compiles -- it
    just resolves against ``sys.path`` instead of the package, so nothing downstream notices
    until the import fails at runtime.  Comparing this set before and after is what stops a
    rewrite from quietly moving an import somewhere else.
    """
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            paths.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
    return paths


def _blank_collapse(lines: list[str]) -> list[str]:
    """At most two blank lines in a row, none at the top, none piled up at the end."""
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line.strip():
            blanks = 0
            out.append(line)
            continue
        blanks += 1
        if out and blanks <= 2:
            out.append(line)
    while len(out) >= 2 and not out[-1].strip() and not out[-2].strip():
        out.pop()
    return out


def strip(root: pathlib.Path, check: bool) -> int:
    """Rewrite every source in memory, prove the result, and only then touch the disk."""
    diag = _diag_names(root)
    module_path = root / "core" / "diagnostics.py"
    sources = {
        path: path.read_text(encoding="utf-8", newline="")
        for path in package_files(root)
        if path != module_path
    }
    report: list[str] = []
    comment_report: list[str] = []
    before_imports: dict[pathlib.Path, set[str]] = {}

    def rel(path: pathlib.Path) -> str:
        return path.relative_to(root).as_posix()

    def rewrite(path: pathlib.Path, edits: list[dict]) -> None:
        notes: list[str] = []
        sources[path] = "".join(
            _blank_collapse(_apply(sources[path].splitlines(keepends=True), edits, notes))
        )
        comment_report.extend(f"{rel(path)}:{note}" for note in notes)

    for path, text in list(sources.items()):
        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            raise Refusal(f"{rel(path)} does not parse before anything was done: {error}")
        before_imports[path] = _module_paths(tree)
        try:
            edits = _collect(tree, diag)
        except Refusal as error:
            raise Refusal(f"{rel(path)}: {error}") from None
        if not edits:
            continue
        for edit in sorted(edits, key=lambda item: item["start"]):
            report.append(
                f"{rel(path)}:{edit['start']} {edit['kind']}"
                + (f" {edit['note']}" if edit["note"] else "")
            )
        rewrite(path, edits)

    for round_index in range(MAX_ROUNDS):
        trees = {}
        for path, text in sources.items():
            try:
                trees[path] = ast.parse(text)
            except SyntaxError as error:
                raise Refusal(f"{rel(path)} does not parse after round {round_index}: {error}")
        global_used: set[str] = set()
        for tree in trees.values():
            global_used |= _loaded_names(tree)

        changed = False
        for path, tree in trees.items():
            edits = _settle_deletions(tree, _dead_locals(tree) + _dead_private_defs(
                tree, global_used
            ) + _import_edits(tree, _loaded_names(tree, imports=False)))
            if not edits:
                continue
            changed = True
            for edit in sorted(edits, key=lambda item: item["start"]):
                report.append(
                    f"{rel(path)}:{edit['start']} {edit['kind']}"
                    f"(r{round_index + 1}) {edit['note']}"
                )
            rewrite(path, edits)
        if not changed:
            break
    else:
        raise Refusal(f"the orphan pass had not settled after {MAX_ROUNDS} rounds")

    by_name = {rel(path): path for path in sources}
    for name, old, new, count in EXPLICIT_PATCHES:
        if name not in by_name:
            raise Refusal(f"{name}: listed in EXPLICIT_PATCHES but not in the tree")
        path = by_name[name]
        # The table is written with bare newlines so it stays readable, and this tree ends
        # its lines with CRLF.  A multi-line pattern in the wrong ending matches nothing,
        # which reads as "the tree moved" rather than as the line-ending mistake it is.
        ending = "\r\n" if "\r\n" in sources[path] else "\n"
        old = old.replace("\r\n", "\n").replace("\n", ending)
        new = new.replace("\r\n", "\n").replace("\n", ending)
        found = sources[path].count(old)
        if found != count:
            raise Refusal(
                f"{name}: expected {count} of {old!r}, found {found} -- the tree moved "
                "since this patch was written"
            )
        sources[path] = sources[path].replace(old, new)
        report.append(f"{name} patch {old[:44]!r}")

    warnings: list[str] = []
    for path, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            raise Refusal(f"{rel(path)} would not compile: {error}")
        compile(tree, str(path), "exec")
        unbound = _unbound_augments(tree)
        if unbound:
            raise Refusal(
                f"{rel(path)} would raise UnboundLocalError: " + "; ".join(unbound)
            )
        for token in GATE_TOKENS:
            if token in text:
                raise Refusal(f"{rel(path)} still mentions {token}")
        if re.search(r"(?<![.\w])print\s*\(", text):
            raise Refusal(f"{rel(path)} still calls print()")
        if re.search(r"^\s*(from|import)\s+\S*diagnostics", text, re.MULTILINE):
            raise Refusal(f"{rel(path)} still imports diagnostics")
        leftover = _import_edits(tree, _loaded_names(tree, imports=False))
        if leftover:
            raise Refusal(
                f"{rel(path)} still imports something nothing uses: "
                + ", ".join(edit["note"] for edit in leftover)
            )
        novel = _module_paths(tree) - before_imports[path]
        if novel:
            raise Refusal(
                f"{rel(path)} now imports {sorted(novel)}, which it never did before"
            )
        for number, line in enumerate(text.splitlines(), start=1):
            if re.search(r"\bdiagnostics?\b", line):
                warnings.append(f"{rel(path)}:{number} prose still says: {line.strip()[:78]}")

    if module_path.exists():
        report.append("core/diagnostics.py delete-module")

    if not check:
        for path, text in sources.items():
            if path.read_text(encoding="utf-8", newline="") != text:
                path.write_text(text, encoding="utf-8", newline="")
        if module_path.exists():
            module_path.unlink()

    for line in report:
        print(line)
    for line in comment_report:
        print(f"comment {line}")
    for line in warnings:
        print(f"warning: {line}")
    print(
        f"\n{'would make' if check else 'made'} {len(report)} edits, "
        f"{len(comment_report)} comments reviewed, {len(warnings)} prose warnings"
    )
    return len(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove the diagnostics layer from a copy of the package."
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent,
        help="the package directory to strip (default: the one holding tools/)",
    )
    parser.add_argument(
        "--check", action="store_true", help="report what would change and write nothing"
    )
    args = parser.parse_args(argv)
    try:
        strip(args.root.resolve(), args.check)
    except Refusal as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
