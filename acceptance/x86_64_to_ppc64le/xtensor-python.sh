#!/bin/bash
# Acceptance test of xtensor-python: the project's unit tests (the xtest
# target). It runs without network on what build.sh left in $BENCH_SRC_DIR
# ($BENCH_CACHE_DIR: scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/xtensor-python
cmake --build "$src/build" --target xtest
