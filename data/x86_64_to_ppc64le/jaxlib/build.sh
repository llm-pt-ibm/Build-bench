#!/bin/bash
# Build recipe for jaxlib 0.10.2 (CPU wheel), following JAX's "Building from
# source" instructions: build/build.py with Bazel, using the XLA source tree in
# this package (--local_xla_path) instead of downloading it. The wheel is left
# in jax/dist; the framework's acceptance test then checks that it works.
# Tools from the build host: $BAZEL, $CLANG, $PYTHON,
# $LOCAL_WHEELS (wheels for this architecture missing from PyPI),
# $BENCH_CACHE_DIR (build state of the run), $BENCH_SHARED_CACHE_DIR
# (content-addressed caches shared by runs), $BENCH_JOBS (parallel jobs).
set -euo pipefail
root=$(pwd)

# jax/WORKSPACE takes local wheels from ../dist
mkdir -p dist
cp "$LOCAL_WHEELS"/*.whl dist/

cd jax
"$PYTHON" build/build.py build --wheels=jaxlib \
  --bazel_path="$BAZEL" \
  --bazel_startup_options="--output_user_root=$BENCH_CACHE_DIR/bazel" \
  --clang_path="$CLANG" \
  --local_xla_path="$root/xla" \
  --bazel_options=--repo_env=ML_WHEEL_TYPE=release \
  --bazel_options=--disk_cache="$BENCH_SHARED_CACHE_DIR/bazel-disk" \
  --bazel_options=--repository_cache="$BENCH_SHARED_CACHE_DIR/bazel-repo" \
  --bazel_options=--keep_going \
  --bazel_options=--jobs="$BENCH_JOBS" \
  --verbose

ls -la dist/jaxlib-*.whl
