"""Prove that a prose rewrite touched prose and nothing else.

Two things are load-bearing here and neither is visible by reading a diff.  The first is the
code: an AST dump with every docstring cut out has to come back identical, which is a much
stronger claim than "it still compiles" and catches a moved default, a flipped comparison, a
renamed local.  The second is the translation keys: the strings inside pgettext() and every
bl_label and bl_description are keys into thirteen locale tables, so changing one character
silently breaks the 50-key parity check and the string stops being translated.

Usage:  python _prose_guard.py before <tree>      # write the baseline
        python _prose_guard.py after  <tree>      # compare against it and report
"""
import ast
import pathlib
import sys

BASELINE = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else pathlib.Path(
    __file__
).resolve().parent / "_prose_baseline.txt"


def files(root):
    for path in sorted(pathlib.Path(root).rglob("*.py")):
        if "__pycache__" in path.parts or "tools" in path.parts:
            continue
        yield path


def cut_docstrings(tree):
    """Drop every string statement so only executable structure is left to compare.

    Not just real docstrings.  This tree also hangs bare strings above its module constants
    to document them, and Python evaluates a string statement and throws it away, so it is
    prose wherever it sits.  Cutting only the first statement of a def would report those as
    code changes and bury the real ones.
    """
    for node in list(ast.walk(tree)):
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if not isinstance(statements, list):
                continue
            kept = [
                item
                for item in statements
                if not (
                    isinstance(item, ast.Expr)
                    and isinstance(item.value, ast.Constant)
                    and isinstance(item.value.value, str)
                )
            ]
            if len(kept) == len(statements):
                continue
            if field == "body" and not kept:
                kept = [ast.Pass()]
            setattr(node, field, kept)
    return tree


def frozen_strings(tree):
    """Every string the translation tables key on, in file order."""
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"pgettext", "npgettext", "dgettext"}
        ):
            out.extend(
                arg.value for arg in node.args if isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
            )
        elif isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if names & {"bl_label", "bl_description"} and isinstance(
                node.value, ast.Constant
            ):
                out.append(node.value.value)
    return out


def snapshot(root):
    """Per file, the code with docstrings cut out and the strings the locales key on."""
    table = {}
    for path in files(root):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        table[path.relative_to(root).as_posix()] = (
            ast.dump(cut_docstrings(ast.parse(text)), annotate_fields=True),
            frozen_strings(tree),
        )
    return table


def main():
    mode, root = sys.argv[1], sys.argv[2]
    current = snapshot(root)
    if mode == "before":
        lines = []
        for name, (dump, strings) in sorted(current.items()):
            lines.append(f"### {name}")
            lines.append("AST " + dump)
            lines.extend("STR " + repr(string) for string in strings)
        BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"baseline written: {BASELINE} ({len(current)} files)")
        return 0

    before = {}
    name = None
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            name = line[4:]
            before[name] = ("", [])
        elif line.startswith("AST "):
            before[name] = (line[4:], before[name][1])
        elif line.startswith("STR "):
            before[name][1].append(ast.literal_eval(line[4:]))

    problems = []
    for name in sorted(set(before) | set(current)):
        if name not in current:
            problems.append(f"{name}: file disappeared")
            continue
        if name not in before:
            problems.append(f"{name}: file is new")
            continue
        old_dump, old_strings = before[name]
        new_dump, new_strings = current[name]
        if old_dump != new_dump:
            problems.append(f"{name}: CODE CHANGED, not just prose")
        if old_strings != new_strings:
            lost = [s for s in old_strings if s not in new_strings]
            gained = [s for s in new_strings if s not in old_strings]
            problems.append(f"{name}: translation keys changed")
            for string in lost[:3]:
                problems.append(f"    lost   {string[:100]!r}")
            for string in gained[:3]:
                problems.append(f"    gained {string[:100]!r}")

    for problem in problems:
        print("FAIL", problem)
    print("GUARD PASS" if not problems else f"GUARD FAIL ({len(problems)} findings)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
