# Build environment "jax-power9": the ppc64le build host for Bazel-based
# Python/ML packages (jax, XLA) on the team's Power9 container.
# Sourced by scripts/script_worker/run.sh before the package's build.sh; the
# model cannot change it, like the build hosts of OBS.
#
# It provides what an x86_64 build host gets from upstream binaries, which do
# not exist for ppc64le: Bazel 7.7.0 (compiled on this host from the release
# sources), clang 17 (conda-forge), Python 3.12 with numpy/scipy, and the
# ppc64le wheels of numpy, ml-dtypes and zstandard (PyPI has none).
#
# The container's system layer (dnf packages, /usr/local/bin, ld.so.conf.d) is
# lost when the container restarts, so it is re-created here when missing.
# Exports: BAZEL, CLANG, PYTHON, TEST_PYTHON, LOCAL_WHEELS, JAVA_HOME.

_conda=/root/miniforge3
_build_env=$_conda/envs/jax_build
_test_env=$_conda/envs/bench_jax_test

if ! command -v javac >/dev/null 2>&1 || ! command -v zip >/dev/null 2>&1 || ! command -v patch >/dev/null 2>&1; then
  dnf install -y java-21-openjdk-devel zip unzip git which patch diffutils >/dev/null 2>&1 \
    || { echo "error: dnf could not install java/zip/patch"; return 1; }
fi
if [ ! -x /usr/local/bin/bazel-7.7.0 ]; then
  cp /root/bazel_source/bazel-7.7.0/bazel-bin/src/bazel_nojdk /usr/local/bin/bazel-7.7.0 \
    && chmod +x /usr/local/bin/bazel-7.7.0 || { echo "error: Bazel 7.7.0 binary missing"; return 1; }
fi
# conda's libstdc++ for tools built with clang 17 (RHEL 8's is too old), and
# the compiler names python-build-standalone's sysconfig expects
if [ ! -f /etc/ld.so.conf.d/zz-conda-jax.conf ]; then
  echo "$_build_env/lib" > /etc/ld.so.conf.d/zz-conda-jax.conf && ldconfig
fi
# (only when missing: run_command_tool's sandbox cannot write there)
_link() { [ "$(readlink "$2")" = "$1" ] || ln -sf "$1" "$2"; }
_link "$_build_env/bin/clang" /usr/local/bin/clang
_link "$_build_env/bin/clang++" /usr/local/bin/clang++
_link "$_build_env/bin/clang" /usr/bin/powerpc64le-linux-gnu-gcc
_link "$_build_env/bin/clang++" /usr/bin/powerpc64le-linux-gnu-g++
# a Python for testing built wheels, without any jax/jaxlib installed
if [ ! -x "$_test_env/bin/python" ]; then
  "$_conda/bin/conda" create -q -y -n bench_jax_test --clone jax_build >/dev/null 2>&1 \
    && "$_test_env/bin/python" -m pip uninstall -q -y jax jaxlib >/dev/null 2>&1 \
    || { echo "error: could not create the test environment"; return 1; }
fi

# test tools for acceptance tests (the JAX test suite runs with pytest)
if ! "$_test_env/bin/python" -c "import pytest, xdist, absl.testing, hypothesis" >/dev/null 2>&1; then
  "$_test_env/bin/python" -m pip install -q pytest pytest-xdist absl-py hypothesis >/dev/null 2>&1 \
    || { echo "error: could not install the test tools"; return 1; }
fi

export JAVA_HOME=$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")
export PATH=/usr/local/bin:$_build_env/bin:$PATH
export BAZEL=/usr/local/bin/bazel-7.7.0
export CLANG=$_build_env/bin/clang
export PYTHON=$_build_env/bin/python
export TEST_PYTHON=$_test_env/bin/python
export LOCAL_WHEELS=/root/jax/dist

echo "BAZEL=$BAZEL ($($BAZEL --version 2>/dev/null))"
echo "CLANG=$CLANG ($($CLANG --version | head -1))"
echo "PYTHON=$PYTHON ($($PYTHON --version 2>&1)); TEST_PYTHON=$TEST_PYTHON (no jax installed; pytest)"
echo "LOCAL_WHEELS=$LOCAL_WHEELS: $(cd "$LOCAL_WHEELS" && ls *.whl | tr '\n' ' ')"
echo "BENCH_CACHE_DIR=$BENCH_CACHE_DIR (build state of this run); BENCH_SHARED_CACHE_DIR=${BENCH_SHARED_CACHE_DIR:-} (shared caches)"
