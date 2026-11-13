#!/bin/bash
# Build recipe for libbullet, as it builds on x86_64: CMake with the unit
# tests, extras and double precision, as the distribution configures it. It
# runs from the case directory in the environment envs/gui-power9, with
# $BENCH_CACHE_DIR (this run's build state), $BENCH_SHARED_CACHE_DIR (caches
# kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd bullet3
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DUSE_DOUBLE_PRECISION=ON -DBUILD_EXTRAS=ON -DBUILD_UNIT_TESTS=ON -DBUILD_BULLET2_DEMOS=ON -DBUILD_OPENGL3_DEMOS=ON -DBUILD_CPU_DEMOS=OFF -DBUILD_PYBULLET=OFF -DBULLET2_MULTITHREADING=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build build --parallel "$BENCH_JOBS"
