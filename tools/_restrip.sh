#!/bin/sh
# Throwaway harness: copy the dev tree to $TEMP/strip_pkg/loop_resample, strip it, report.
# The folder is named loop_resample so the smoke test can import it as a plain package, and
# only what blender_manifest.toml ships is copied -- tools/ and tests/ stay behind, as they
# would in the zip.
set -e
DEV=$(cd "$(dirname "$0")/.." && pwd)
PKG="$TEMP/strip_pkg/loop_resample"
rm -rf "$TEMP/strip_pkg"
mkdir -p "$PKG"
cd "$DEV"
for item in __init__.py blender_manifest.toml operators.py core i18n icons shape ui; do
  cp -r "$item" "$PKG/"
done
find "$TEMP/strip_pkg" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
cd "$PKG"
python "$DEV/tools/strip_diagnostics.py" --root . "$@"
