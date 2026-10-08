#!/bin/sh
# Rebuild BTRun.exe with PyInstaller and re-assemble the portable
# distribution folder dist/BTRun (PyInstaller wipes it on every rebuild).
# Run this from the LLM_BT_Gen folder in Git Bash:
#   sh build_dist.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
VENV_PY="$ROOT/behaverify_venv/Scripts/python.exe"
CONDA_BIN="D:/software/anaconda/Library/bin"
DIST="$HERE/dist/BTRun"

echo "== building BTRun.exe =="
"$VENV_PY" -m PyInstaller --noconfirm --clean --name BTRun --onedir --console \
    --paths "$ROOT/behaverify/src" \
    --collect-all behaverify --collect-all textX \
    --exclude-module tkinter \
    --add-binary "$CONDA_BIN/libexpat.dll;." \
    --add-binary "$CONDA_BIN/liblzma.dll;." \
    --add-binary "$CONDA_BIN/LIBBZ2.dll;." \
    --add-binary "$CONDA_BIN/ffi.dll;." \
    "$HERE/bt_bench_run.py" > "$HERE/pyinstaller_build.log" 2>&1
tail -2 "$HERE/pyinstaller_build.log"

echo "== assembling dist/BTRun =="
cp -r "$ROOT/NuSMV-2.7.1-win64/NuSMV-2.7.1-win64" "$DIST/NuSMV"
mkdir -p "$DIST/benchmarks" "$DIST/selftest"
cp "$ROOT/behaverify/Benchmark/Behaverify_benchmark_hard.xlsx" "$DIST/benchmarks/"
cp "$HERE/complex_tasks.xlsx" "$DIST/benchmarks/"
cp "$HERE/prompt_behaverify.txt" "$DIST/"
cp "$ROOT/behaverify/Benchmark/trees/ABC3.tree" "$DIST/selftest/selftest.tree"
cp "$HERE/README_dist.txt" "$DIST/README.txt"
ls "$DIST"
echo "== done: $DIST =="
