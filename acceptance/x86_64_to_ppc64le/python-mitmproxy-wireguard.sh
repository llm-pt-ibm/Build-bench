#!/bin/bash
# Acceptance test of python-mitmproxy-wireguard: the wheel installs and its
# module imports. It runs without network on what build.sh left in
# $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit status
# 0.
set -euo pipefail
src=$BENCH_SRC_DIR/mitmproxy_wireguard
wheel=$(ls "$src"/dist/*.whl 2>/dev/null | head -1)
[ -n "$wheel" ] || { echo "error: the build left no wheel in dist/"; exit 1; }
venv=$BENCH_CACHE_DIR/acceptance-venv
rm -rf "$venv"
"${TEST_PYTHON:-python3}" -m venv --system-site-packages "$venv"
"$venv/bin/pip" install -q --no-deps --no-index "$wheel"
cd "$BENCH_CACHE_DIR"
"$venv/bin/python" -c "import mitmproxy_wireguard; print('mitmproxy_wireguard imported')"
