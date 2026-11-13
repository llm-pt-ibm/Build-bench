#!/bin/bash
# Build recipe for python-PySDL2, as it builds on x86_64: a wheel built by pip
# (no build isolation). It runs from the case directory in the environment
# envs/py-power9, with $BENCH_CACHE_DIR (this run's build state),
# $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd pysdl2
"${PYTHON:-python3}" -m pip wheel --no-deps --no-build-isolation -w dist .
ls dist/*.whl
