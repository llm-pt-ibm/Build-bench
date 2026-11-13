#!/bin/bash
# Acceptance test of bash-completion-doc: the completion tests of gcc (pytest;
# the others need users, network interfaces and programs the container lacks).
# It runs without network on what build.sh left in $BENCH_SRC_DIR
# ($BENCH_CACHE_DIR: scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/bash-completion
cd "$src/test"
"${TEST_PYTHON:-python3}" -m pytest -q -p no:cacheprovider t/test_gcc.py
