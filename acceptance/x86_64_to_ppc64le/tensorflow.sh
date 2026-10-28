#!/bin/bash
# Acceptance test of tensorflow: install the built wheel in a clean Python (no
# network: the test environment has its dependencies) and check it against
# NumPy: float32, float64, float16, bfloat16, int8 (also in an XLA-compiled
# function), gradients and a small Keras training. Each check runs in its own
# process, so a crash in one is reported and the others still run.
set -uo pipefail
wheel=$(ls "$BENCH_SRC_DIR"/tensorflow/bazel-bin/tensorflow/tools/pip_package/wheel_house/*.whl 2>/dev/null | head -1)
[ -n "$wheel" ] || { echo "error: the build left no wheel in tensorflow/bazel-bin/tensorflow/tools/pip_package/wheel_house"; exit 1; }
echo "testing $(basename "$wheel")"
venv=$BENCH_CACHE_DIR/acceptance-venv
rm -rf "$venv"
"$TEST_PYTHON" -m venv --system-site-packages "$venv" || exit 1
"$venv/bin/pip" install -q --no-deps --no-index "$wheel" || { echo "error: installing the wheel failed"; exit 1; }
cd "$BENCH_CACHE_DIR"   # not the source tree, so that tensorflow is imported from the venv
cat > tf_checks.py <<'PY'
import sys
import numpy as np
rng = np.random.default_rng(0)
A = rng.standard_normal((64, 64)).astype(np.float32)
B = rng.standard_normal((64, 64)).astype(np.float32)
I8 = rng.integers(-128, 128, 1000, dtype=np.int8)

def import_and_device():
    import tensorflow as tf
    assert tf.config.list_physical_devices("CPU")

def float32_ops():
    import tensorflow as tf
    np.testing.assert_allclose(tf.matmul(A, B).numpy(), A @ B, rtol=1e-4, atol=1e-4)
    np.testing.assert_allclose(tf.nn.softmax(A).numpy().sum(1), np.ones(64), rtol=1e-5)

def float64_ops():
    import tensorflow as tf
    m = A.astype(np.float64) @ A.T.astype(np.float64) + 64 * np.eye(64)
    np.testing.assert_allclose(tf.linalg.inv(m).numpy(), np.linalg.inv(m), rtol=1e-8, atol=1e-12)

def float16():
    import tensorflow as tf
    h = A.astype(np.float16)
    np.testing.assert_allclose(tf.add(h, h).numpy(), h + h)

def bfloat16():
    import tensorflow as tf
    back = tf.cast(tf.cast(A, tf.bfloat16), tf.float32).numpy()
    assert np.max(np.abs(back - A)) <= 0.01 * np.max(np.abs(A)), np.max(np.abs(back - A))
    prod = tf.matmul(tf.cast(A, tf.bfloat16), tf.cast(B, tf.bfloat16))
    np.testing.assert_allclose(tf.cast(prod, tf.float32).numpy(), A @ B, rtol=0.05, atol=0.5)

def int8():
    import tensorflow as tf
    np.testing.assert_array_equal(tf.cast(I8, tf.int32).numpy(), I8.astype(np.int32))
    twice = tf.function(lambda x: tf.cast(x, tf.float32) * 2.0, jit_compile=True)
    np.testing.assert_array_equal(twice(I8).numpy(), I8.astype(np.float32) * 2.0)

def gradients():
    import tensorflow as tf
    x = tf.Variable(3.0)
    with tf.GradientTape() as tape:
        y = x * x
    assert abs(tape.gradient(y, x).numpy() - 6.0) < 1e-6

def keras_training():
    import tensorflow as tf
    X = rng.standard_normal((256, 8)).astype(np.float32)
    Y = X.sum(1, keepdims=True)
    model = tf.keras.Sequential([tf.keras.Input((8,)), tf.keras.layers.Dense(16, activation="relu"),
                                 tf.keras.layers.Dense(1)])
    model.compile(optimizer="adam", loss="mse")
    loss = model.fit(X, Y, epochs=30, verbose=0).history["loss"]
    assert loss[-1] < 0.5 * loss[0], loss

CHECKS = [import_and_device, float32_ops, float64_ops, float16, bfloat16, int8, gradients, keras_training]
if len(sys.argv) > 1:
    globals()[sys.argv[1]]()
else:
    print(" ".join(c.__name__ for c in CHECKS))
PY
failed=0
for check in $("$venv/bin/python" tf_checks.py); do
  out=$("$venv/bin/python" tf_checks.py "$check" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then
    echo "PASS $check"
  else
    echo "FAIL $check (exit status $rc)"
    echo "$out" | tail -15 | sed 's/^/    /'
    failed=$((failed + 1))
  fi
done
echo "acceptance: $failed check(s) failed"
[ $failed -eq 0 ]
