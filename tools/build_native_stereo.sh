#!/usr/bin/env bash
# Ubuntu 22.04; work/source is a verified snapshot, never the Windows authority.
set -euo pipefail
work="$(realpath "${1:?Usage: bash build_native_stereo.sh WORK [JOBS]}")"
jobs="${2:-2}"
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || exit 2
src="$work/source"
test -f "$src/CMakeLists.txt"
revision=dd801d244db3a8e27b7fe8020cd751404aa818fd
mkdir -p "$work/deps" "$work/build" "$work/install"
if [ ! -e "$work/deps/Pangolin" ]; then
    git clone --branch v0.6 --depth 1 https://github.com/stevenlovegrove/Pangolin.git "$work/deps/Pangolin"
fi
test "$(git -C "$work/deps/Pangolin" rev-parse HEAD)" = "$revision"
test -z "$(git -C "$work/deps/Pangolin" status --porcelain --untracked-files=no)"
cmake -S "$work/deps/Pangolin" -B "$work/build/pangolin" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$work/install" -DBUILD_EXAMPLES=OFF -DBUILD_TOOLS=OFF -DBUILD_PANGOLIN_PYTHON=OFF
cmake --build "$work/build/pangolin" --parallel "$jobs"
cmake --install "$work/build/pangolin"
cmake -S "$src/Thirdparty/DBoW2" -B "$work/build/dbow2" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$work/build/dbow2" --parallel "$jobs"
cmake -S "$src/Thirdparty/Sophus" -B "$work/build/sophus" -G Ninja -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF
cmake --build "$work/build/sophus" --parallel "$jobs"
if [ ! -e "$src/Vocabulary/ORBvoc.txt" ]; then
    tar -xzf "$src/Vocabulary/ORBvoc.txt.tar.gz" -C "$src/Vocabulary"
fi
cmake -S "$src" -B "$work/build/orb" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$work/install"
cmake --build "$work/build/orb" --target g2o ORB_SLAM3 stereo_euroc --parallel "$jobs"
ldd "$src/Examples/Stereo/stereo_euroc" > "$work/build/stereo-dependencies.txt"
cat "$work/build/stereo-dependencies.txt"
if grep -q 'not found' "$work/build/stereo-dependencies.txt"; then exit 1; fi
