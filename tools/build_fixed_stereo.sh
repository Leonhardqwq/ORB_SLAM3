#!/usr/bin/env bash
# Build in an isolated snapshot, reusing only the baseline's DBoW2/Pangolin.
set -euo pipefail
work="$(realpath "${1:?Usage: bash build_fixed_stereo.sh WORK BASELINE [JOBS]}")"
baseline="$(realpath "${2:?Supply the existing native dependency workspace}")"
jobs="${3:-2}"
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || exit 2
test "$work" != "$baseline"
src="$work/source"
test -f "$src/Examples/Stereo/stereo_fixed_replay.cc"
test -f "$baseline/source/Thirdparty/DBoW2/lib/libDBoW2.so"
test -d "$baseline/install"
python3 - "$src" "$baseline/source" <<'PY'
from pathlib import Path
import sys,shutil
new,old=(Path(x).resolve() for x in sys.argv[1:])
assert new!=old
for path in (old/'Thirdparty/DBoW2').rglob('*'):
    if path.is_file() and path.suffix in {'.h','.cpp'} and 'build' not in path.parts:
        peer=new/path.relative_to(old)
        assert peer.read_bytes()==path.read_bytes(), 'Dependency source mismatch: '+str(peer)
source=old/'Thirdparty/DBoW2/lib/libDBoW2.so'
dest=new/'Thirdparty/DBoW2/lib/libDBoW2.so'
dest.parent.mkdir(parents=True,exist_ok=True)
if dest.exists(): assert dest.read_bytes()==source.read_bytes(), 'Use a fresh snapshot'
else: shutil.copyfile(source,dest)
PY
if [ ! -e "$src/Vocabulary/ORBvoc.txt" ]; then
    tar -xzf "$src/Vocabulary/ORBvoc.txt.tar.gz" -C "$src/Vocabulary"
fi
cmake -S "$src" -B "$work/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$baseline/install"
cmake --build "$work/build" --target stereo_euroc stereo_fixed_replay --parallel "$jobs"
ldd "$src/Examples/Stereo/stereo_fixed_replay" > "$work/build/fixed-dependencies.txt"
if grep -q 'not found' "$work/build/fixed-dependencies.txt"; then
    cat "$work/build/fixed-dependencies.txt"; exit 1
fi
