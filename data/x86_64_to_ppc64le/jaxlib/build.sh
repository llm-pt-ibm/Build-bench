#!/bin/bash
# Build recipe for jaxlib 0.10.2 (CPU wheel), following JAX's "Building from
# source" instructions: build/build.py with Bazel, using the XLA source tree in
# this package (--local_xla_path) instead of downloading it. Then, like an RPM
# %check, the wheel is installed with jax from this source tree in a clean
# Python and a small program is run.
# Tools from the build host: $BAZEL, $CLANG, $PYTHON, $TEST_PYTHON,
# $LOCAL_WHEELS (wheels for this architecture missing from PyPI),
# $BENCH_CACHE_DIR (persistent cache), $BENCH_JOBS (parallel jobs).
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
  --bazel_options=--keep_going \
  --bazel_options=--jobs="$BENCH_JOBS" \
  --verbose

echo "=== check: install the wheel and run a program"
wheel=$(ls dist/jaxlib-*.whl)
venv=$BENCH_CACHE_DIR/test-venv
rm -rf "$venv"
"$TEST_PYTHON" -m venv --system-site-packages "$venv"
"$venv/bin/pip" install -q --no-deps --no-build-isolation "$wheel" "$root/jax"
"$venv/bin/python" - <<'PY'
import jax, jax.numpy as jnp, jaxlib
print("jax", jax.__version__, "jaxlib", jaxlib.__version__, "from", jaxlib.__file__)
x = jnp.arange(12.0).reshape(3, 4)
assert float(jnp.sum(x)) == 66.0
assert float(jax.jit(lambda a: (a @ a.T).mean())(x)) == 126.0
print(jax.grad(lambda a: jnp.tanh(a).sum())(jnp.ones(3)))
print("check passed on", jax.devices())
PY
