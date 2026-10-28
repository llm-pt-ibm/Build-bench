#!/bin/bash
# Build recipe for TensorFlow 2.21.0 (CPU wheel), as on an x86_64 build host:
# ./configure without prompts, then Bazel's wheel target with clang. The wheel
# is left in tensorflow/bazel-bin/tensorflow/tools/pip_package/wheel_house,
# where the acceptance test takes it from.
# Tools from the build host: $BAZEL, $CLANG, $PYTHON; $BENCH_CACHE_DIR,
# $BENCH_SHARED_CACHE_DIR and $BENCH_JOBS come from the framework.
set -euo pipefail
cd tensorflow
# TensorFlow's configure looks for "bazel" in PATH
mkdir -p "$BENCH_CACHE_DIR/bin" && ln -sf "$BAZEL" "$BENCH_CACHE_DIR/bin/bazel"
export PATH="$BENCH_CACHE_DIR/bin:$PATH"
export PYTHON_BIN_PATH="$PYTHON" TF_PYTHON_VERSION=3.12 TF_NEED_CUDA=0 TF_NEED_ROCM=0 \
       TF_NEED_CLANG=1 CLANG_COMPILER_PATH="$CLANG" CC_OPT_FLAGS="-Wno-sign-compare" TF_SET_ANDROID_WORKSPACE=0
(yes "" || true) | ./configure
bazel --output_user_root="$BENCH_CACHE_DIR/bazel" build //tensorflow/tools/pip_package:wheel \
  --config=opt --repo_env=WHEEL_NAME=tensorflow_cpu \
  --disk_cache="$BENCH_SHARED_CACHE_DIR/bazel-disk" \
  --repository_cache="$BENCH_SHARED_CACHE_DIR/bazel-repo" \
  --jobs="$BENCH_JOBS" --keep_going
ls -la bazel-bin/tensorflow/tools/pip_package/wheel_house/*.whl
