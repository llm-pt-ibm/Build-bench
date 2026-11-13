#!/bin/bash
# Build recipe for json-schema-validator, as it builds on x86_64: CMake with
# the tests, without the examples. It runs from the case directory in the
# environment envs/c-power9, with $BENCH_CACHE_DIR (this run's build state),
# $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd json-schema-validator
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DJSON_VALIDATOR_BUILD_TESTS=ON -DJSON_VALIDATOR_BUILD_EXAMPLES=OFF
cmake --build build --parallel "$BENCH_JOBS"
