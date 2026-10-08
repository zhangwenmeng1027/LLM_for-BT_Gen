#!/bin/sh
# Rebuild the portable Linux BTRun distribution (Ubuntu 22.04+, x86_64).
#
# Runs INSIDE Linux -- e.g. from Windows Git Bash:
#   wsl.exe -d Ubuntu-22.04 -e sh -c 'sh /mnt/d/<path>/LLM_BT_Gen/build_dist_linux.sh'
#
# NOTE on NuSMV: the official NuSMV-2.7.1-linux64.tar.xz prebuilt binaries
# require GLIBC 2.38 (Ubuntu 24.04) and are NOT usable on Ubuntu 22.04.
# This script therefore COMPILES NuSMV 2.7.1 from source on the build host
# (Ubuntu 22.04 / glibc 2.35), links it against system libedit, and bundles
# libedit.so.2 + libbsd.so.0 + libmd.so.0 next to it.  The resulting
# executable runs on any Ubuntu 22.04+ (or glibc >= 2.35) machine with no
# packages installed.
#
# Output:  dist/BTRun-linux/  (folder)  +  dist/BTRun-linux-x64.tar.gz
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"                    # LLM_for-BT_Gen checkout root
B="$HOME/btrun_build"                        # ext4 build workspace
VENV="$B/venv/bin"

# ---- 0. system build dependencies (run once, needs root) -------------------
# apt-get install -y build-essential ninja-build bison flex libedit-dev \
#                    python3-venv python3-pip xz-utils

# ---- 1. workspace -----------------------------------------------------------
mkdir -p "$B/behaverify_repo" "$B/app" "$B/app/selftest" "$B/nusmv-src"
cp "$ROOT/behaverify/pyproject.toml" "$ROOT/behaverify/README.md" \
   "$ROOT/behaverify/MANIFEST.in" "$B/behaverify_repo/"
rm -rf "$B/behaverify_repo/src"
cp -r "$ROOT/behaverify/src" "$B/behaverify_repo/"
cp "$HERE/bt_bench_run.py" "$HERE/prompt_behaverify.txt" \
   "$HERE/complex_tasks.xlsx" "$B/app/"
cp "$ROOT/behaverify/Benchmark/Behaverify_benchmark_hard.xlsx" "$B/app/"
cp "$ROOT/behaverify/Benchmark/trees/ABC3.tree" "$B/app/selftest/selftest.tree"

# ---- 2. python environment --------------------------------------------------
if [ ! -x "$VENV/python" ]; then
    python3 -m venv "$B/venv"
    "$VENV/pip" install --upgrade pip
fi
"$VENV/pip" install -q "$B/behaverify_repo" pyinstaller openpyxl meson

# ---- 3. compile NuSMV 2.7.1 from source (glibc 2.35 target) -----------------
# with-shell MUST stay enabled: NuSMV executes -source scripts through its
# interactive-shell machinery even in batch mode.  libxml2/gtest/docs off.
if [ ! -x "$B/nusmv-src/build/NuSMV" ]; then
    cd "$B/nusmv-src"
    rm -rf NuSMV-2.7.1 build
    cp "$ROOT/NuSMV-2.7.1-src.tar.xz" .
    tar -xJf NuSMV-2.7.1-src.tar.xz
    mv NuSMV-2.7.1/* .
    rmdir NuSMV-2.7.1
    export PATH="$B/venv/bin:$PATH"      # meson + unversioned 'python'
    "$VENV/meson" setup build --buildtype release \
        -Dbuild-doc=disabled -Dwith-libxml2=disabled -Dwith-gtest=disabled \
        > "$B/nusmv_build.log" 2>&1
    "$VENV/meson" compile -C build >> "$B/nusmv_build.log" 2>&1
fi

# ---- 4. PyInstaller ---------------------------------------------------------
cd "$B/app"
"$VENV/pyinstaller" --noconfirm --clean --name BTRun --onedir --console \
    --collect-all behaverify --collect-all textX \
    --exclude-module tkinter \
    bt_bench_run.py > "$B/pyinstaller_build.log" 2>&1 || {
        tail -30 "$B/pyinstaller_build.log"; exit 1; }
tail -2 "$B/pyinstaller_build.log"

# ---- 5. assemble the distribution folder (on ext4, keeps +x bits) ----------
DIST="$B/BTRun-linux"
rm -rf "$DIST"
mkdir -p "$DIST" "$DIST/NuSMV/bin" "$DIST/NuSMV/lib" "$DIST/benchmarks" \
         "$DIST/selftest"
cp -r "$B/app/dist/BTRun/." "$DIST/"
cp "$B/nusmv-src/build/NuSMV"     "$DIST/NuSMV/bin/NuSMV"
cp "$B/nusmv-src/build/ltl2smv"   "$DIST/NuSMV/bin/ltl2smv"
chmod +x "$DIST/NuSMV/bin/NuSMV" "$DIST/NuSMV/bin/ltl2smv"
# runtime shared libraries for NuSMV (loaded via LD_LIBRARY_PATH set by BTRun)
for L in libedit.so.2 libbsd.so.0 libmd.so.0; do
    cp "/lib/x86_64-linux-gnu/$L" "$DIST/NuSMV/lib/"
done
cp "$ROOT/behaverify/Benchmark/Behaverify_benchmark_hard.xlsx" "$DIST/benchmarks/"
cp "$HERE/complex_tasks.xlsx" "$DIST/benchmarks/"
cp "$HERE/prompt_behaverify.txt" "$DIST/"
cp "$B/app/selftest/selftest.tree" "$DIST/selftest/"
cp "$HERE/README_dist_linux.txt" "$DIST/README.txt"
chmod +x "$DIST/BTRun"

# ---- 6. tarball (created on ext4 so the +x bits survive) --------------------
cd "$B"
rm -f BTRun-linux-x64.tar.gz
tar -czf BTRun-linux-x64.tar.gz BTRun-linux
ls -la "$B/BTRun-linux-x64.tar.gz"
mkdir -p "$HERE/dist"
rm -rf "$HERE/dist/BTRun-linux"
cp -r "$DIST" "$HERE/dist/BTRun-linux"
cp "$B/BTRun-linux-x64.tar.gz" "$HERE/dist/"
echo "== done: $HERE/dist/BTRun-linux + $HERE/dist/BTRun-linux-x64.tar.gz =="
