#!/bin/bash
# Build recipe for librealsense, as it builds on x86_64: CMake as the
# distribution configures it, with fastcdr and libdeflate (../fastcdr,
# ../libdeflate) where the build would download them. It runs from the case
# directory in the environment envs/gui-power9, with $BENCH_CACHE_DIR (this
# run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs) and
# $BENCH_JOBS.
set -euo pipefail
cd librealsense
mkdir -p build/third-party
ln -sfn ../../../fastcdr build/third-party/fastcdr
ln -sfn ../../../libdeflate build/third-party/libdeflate
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCHECK_FOR_UPDATES=OFF -DIMPORT_DEPTH_CAM_FW=OFF -DUSE_EXTERNAL_NLOHMANN_JSON=ON -DBUILD_GRAPHICAL_EXAMPLES=OFF -DBUILD_EXAMPLES=ON
cmake --build build --parallel "$BENCH_JOBS"
