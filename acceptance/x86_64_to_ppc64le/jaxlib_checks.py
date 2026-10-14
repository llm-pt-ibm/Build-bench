"""Checks of the jaxlib acceptance test (jaxlib.sh). Usage:
  python jaxlib_checks.py --list     names of the checks
  python jaxlib_checks.py <check>    run one check (exit status 0: passed)
Reference values come from NumPy/SciPy, and the PRNG values from the official
jax/jaxlib 0.10.2 wheels on x86_64."""
import sys

import numpy as np

# jax.random outputs of jax 0.10.2 on x86_64 (threefry, default settings)
X86_PRNG = {
    "split_key_data": [[1797259609, 2579123966], [928981903, 3453687069], [4146024105, 2718843009]],
    "bits_u32": [2098992034, 2919706841, 2646866425, 2409546199, 1935504149, 2516274904, 321304473, 3329172656],
    "randint": [99, 22, 0, 37, 22, 86, 84, 54],
    "uniform_f32_bits": [1064475214, 1064993846, 1051337244, 1055913296, 1058137146, 1042905504],
    "normal_f32": [-0.15443718433380127, 0.08470727503299713, -0.135980486869812, -0.15503625571727753,
                   1.266667366027832, 0.14829757809638977],
    "permutation": [0, 5, 6, 7, 4, 2, 1, 3, 9, 8],
}


def rel_err(got, want):
    kind = np.complex128 if np.iscomplexobj(got) or np.iscomplexobj(want) else np.float64
    got, want = np.asarray(got).astype(kind), np.asarray(want).astype(kind)
    return float(np.max(np.abs(got - want)) / max(float(np.max(np.abs(want))), 1e-30))


def expect(cond, message):
    if not cond:
        raise AssertionError(message)


def close(name, got, want, tol):
    err = rel_err(got, want)
    expect(err <= tol, f"{name}: relative error {err:.3g} > {tol:g}\n  got  {np.asarray(got).ravel()[:8]}\n"
                       f"  want {np.asarray(want).ravel()[:8]}")


def import_and_device():
    import jax
    import jaxlib
    print("jax", jax.__version__, "jaxlib", jaxlib.__version__, "from", jaxlib.__file__, jax.devices())
    expect(jaxlib.__version__ == "0.10.2", f"jaxlib version {jaxlib.__version__}, expected 0.10.2")
    expect("acceptance-venv" in jaxlib.__file__, "jaxlib was not imported from the tested wheel")
    expect(jax.devices()[0].platform == "cpu", f"no CPU device: {jax.devices()}")


def float32_ops():
    import jax
    import jax.numpy as jnp
    rng = np.random.default_rng(0)
    a, b = rng.standard_normal((64, 48), np.float32), rng.standard_normal((48, 32), np.float32)
    close("matmul", jnp.dot(a, b), a.astype(np.float64) @ b, 1e-5)
    x = rng.standard_normal(1000).astype(np.float32)
    f = jax.jit(lambda v: jnp.tanh(v) * jnp.exp(-v * v) + jnp.log1p(jnp.abs(v)) + jnp.sin(v) ** 2)
    close("fused transcendental", f(x), np.tanh(x) * np.exp(-x * x) + np.log1p(np.abs(x)) + np.sin(x) ** 2, 1e-5)
    close("sum", jnp.sum(x), x.astype(np.float64).sum(), 1e-5)
    close("cumsum", jnp.cumsum(x), np.cumsum(x.astype(np.float64)), 1e-4)
    close("max/argmax", [jnp.max(x), jnp.argmax(x)], [x.max(), x.argmax()], 0)


def float64_ops():
    import jax
    jax.config.update("jax_enable_x64", True)
    import jax.numpy as jnp
    rng = np.random.default_rng(1)
    a, b = rng.standard_normal((40, 40)), rng.standard_normal((40, 3))
    expect(jnp.asarray(a).dtype == jnp.float64, "x64 mode is not active")
    close("matmul f64", jnp.dot(a, b), a @ b, 1e-12)
    close("solve f64", jnp.linalg.solve(a, b), np.linalg.solve(a, b), 1e-9)
    close("exp/log f64", jax.jit(lambda v: jnp.exp(jnp.log1p(v * v)))(a), np.exp(np.log1p(a * a)), 1e-12)


def linalg():
    import jax.numpy as jnp
    rng = np.random.default_rng(2)
    m = rng.standard_normal((32, 32)).astype(np.float32)
    spd = m @ m.T + 32 * np.eye(32, dtype=np.float32)
    close("cholesky", jnp.linalg.cholesky(spd), np.linalg.cholesky(spd.astype(np.float64)), 1e-4)
    close("svd", jnp.linalg.svd(m, compute_uv=False), np.linalg.svd(m.astype(np.float64), compute_uv=False), 1e-4)
    close("eigh", jnp.linalg.eigh(spd)[0], np.linalg.eigh(spd.astype(np.float64))[0], 1e-4)
    rhs = rng.standard_normal((32, 2)).astype(np.float32)
    close("solve", jnp.linalg.solve(spd, rhs), np.linalg.solve(spd.astype(np.float64), rhs), 1e-4)
    close("det", jnp.linalg.det(spd / 32), np.linalg.det(spd.astype(np.float64) / 32), 1e-3)


def fft_and_convolution():
    import jax
    import jax.numpy as jnp
    from scipy import signal
    rng = np.random.default_rng(3)
    x = rng.standard_normal(256).astype(np.float32)
    close("fft", jnp.fft.fft(x), np.fft.fft(x.astype(np.float64)), 1e-4)
    close("irfft(rfft)", jnp.fft.irfft(jnp.fft.rfft(x), n=256), x, 1e-5)
    k = rng.standard_normal(9).astype(np.float32)
    close("convolve", jnp.convolve(x, k), np.convolve(x.astype(np.float64), k), 1e-5)
    img, ker = rng.standard_normal((1, 1, 20, 20)).astype(np.float32), rng.standard_normal((1, 1, 3, 3)).astype(np.float32)
    out = jax.lax.conv_general_dilated(img, ker, (1, 1), "VALID")
    close("conv2d", out[0, 0], signal.correlate2d(img[0, 0].astype(np.float64), ker[0, 0], mode="valid"), 1e-5)


def float16():
    import jax
    import jax.numpy as jnp
    rng = np.random.default_rng(4)
    a = rng.standard_normal((32, 32)).astype(np.float16)
    b = rng.standard_normal((32, 32)).astype(np.float16)
    a32, b32 = a.astype(np.float32), b.astype(np.float32)
    close("f16 arithmetic", jax.jit(lambda x, y: x * y + x)(a, b), a32 * b32 + a32, 2e-3)
    close("f16 matmul", jax.jit(jnp.dot)(a, b), a32 @ b32, 2e-2)
    close("f32->f16->f32", jnp.asarray(a32).astype(jnp.float16).astype(jnp.float32), a32, 0)


def bfloat16():
    import jax
    import jax.numpy as jnp
    import ml_dtypes
    rng = np.random.default_rng(5)
    a32 = rng.standard_normal((32, 32)).astype(np.float32)
    b32 = rng.standard_normal((32, 32)).astype(np.float32)
    a, b = a32.astype(ml_dtypes.bfloat16), b32.astype(ml_dtypes.bfloat16)
    expect(np.array_equal(np.asarray(jnp.asarray(a32).astype(jnp.bfloat16)).view(np.uint16), a.view(np.uint16)),
           "f32 -> bf16 conversion differs from ml_dtypes")
    close("bf16 -> f32", jnp.asarray(a).astype(jnp.float32), a.astype(np.float32), 0)
    af, bf = a.astype(np.float32), b.astype(np.float32)
    close("bf16 arithmetic (jit)", jax.jit(lambda x, y: x * y + x)(a, b), af * bf + af, 1e-2)
    close("bf16 matmul (jit)", jax.jit(jnp.dot)(a, b), af @ bf, 3e-2)
    close("bf16 reduction", jnp.sum(jnp.asarray(a), dtype=jnp.float32), af.astype(np.float64).sum(), 1e-2)

    def attention(q, k, v):
        w = jax.nn.softmax(q @ k.T / 8.0, axis=-1)
        return w @ v
    want = attention(af, bf, af)
    close("bf16 attention (jit)", jax.jit(attention)(a, b, a).astype(jnp.float32), want, 5e-2)


def int8():
    import jax
    import jax.numpy as jnp
    import jax.scipy.linalg as jsl
    from scipy import linalg
    x = np.array([-128, -100, -4, -1, 0, 1, 4, 100, 127], np.int8)
    f = np.linspace(-1, 1, 9).astype(np.float32)
    close("int8 -> f32", jnp.asarray(x).astype(jnp.float32), x.astype(np.float32), 0)
    close("int8 -> f32 in a fused kernel", jax.jit(lambda a, b: a + b.astype(jnp.float32) * 2.0)(f, x),
          f + x.astype(np.float32) * 2.0, 0)
    close("concat f32 with int8 (jit)", jax.jit(lambda a, b: jnp.concatenate([a, b.astype(jnp.float32)]) * 0.5)(f, x),
          np.concatenate([f, x.astype(np.float32)]) * 0.5, 0)
    close("toeplitz of int8 (jit)", jax.jit(lambda c: jsl.toeplitz(c).astype(jnp.float32) * 1.5)(x),
          linalg.toeplitz(x).astype(np.float32) * 1.5, 0)
    close("int8 matmul -> int32", jnp.dot(x[None, :], x[:, None], preferred_element_type=jnp.int32),
          x.astype(np.int32)[None, :] @ x.astype(np.int32)[:, None], 0)
    close("f32 -> int8 (jit)", jax.jit(lambda a: (a * 100).astype(jnp.int8))(f), (f * 100).astype(np.int8), 0)


def prng_golden():
    import jax
    import jax.numpy as jnp
    key = jax.random.key(0)
    got = {
        "split_key_data": np.asarray(jax.random.key_data(jax.random.split(key, 3))).tolist(),
        "bits_u32": np.asarray(jax.random.bits(jax.random.key(42), (8,), dtype=jnp.uint32)).tolist(),
        "randint": np.asarray(jax.random.randint(jax.random.key(7), (8,), 0, 100)).tolist(),
        "uniform_f32_bits": np.asarray(jax.random.uniform(key, (6,), dtype=jnp.float32)).view(np.uint32).tolist(),
        "permutation": np.asarray(jax.random.permutation(jax.random.key(3), 10)).tolist(),
    }
    for name, values in got.items():
        expect(values == X86_PRNG[name], f"{name} differs from x86_64:\n  got  {values}\n  want {X86_PRNG[name]}")
    close("normal", jax.random.normal(jax.random.key(1), (6,), dtype=jnp.float32), X86_PRNG["normal_f32"], 1e-6)


def gradients():
    import jax
    import jax.numpy as jnp
    x = np.linspace(-2, 2, 7).astype(np.float32)
    close("grad tanh", jax.grad(lambda v: jnp.tanh(v).sum())(x), 1 - np.tanh(x) ** 2, 1e-5)
    close("hessian", jax.hessian(lambda v: (v ** 3).sum())(x), np.diag(6 * x), 1e-5)
    m = np.arange(12, dtype=np.float32).reshape(3, 4)
    close("vmap", jax.vmap(lambda r: jnp.dot(r, r))(m), (m * m).sum(1), 0)
    close("jit(grad(mean(a @ a.T)))", jax.jit(jax.grad(lambda a: (a @ a.T).mean()))(m),
          np.broadcast_to(2 * m.sum(0) / 9, m.shape), 1e-6)


def mlp_training():
    import jax
    import jax.numpy as jnp
    rng = np.random.default_rng(6)
    n = 400
    x = np.concatenate([rng.normal(-1.5, 0.6, (n, 2)), rng.normal(1.5, 0.6, (n, 2))]).astype(np.float32)
    y = np.concatenate([np.zeros(n), np.ones(n)]).astype(np.int32)
    k1, k2 = jax.random.split(jax.random.key(0))
    params = [jax.random.normal(k1, (2, 32)) * 0.5, jnp.zeros(32), jax.random.normal(k2, (32, 2)) * 0.5, jnp.zeros(2)]

    def loss(p, xb, yb):
        h = jnp.tanh(xb @ p[0] + p[1])
        logits = h @ p[2] + p[3]
        return -jnp.mean(jax.nn.log_softmax(logits)[jnp.arange(yb.shape[0]), yb])

    step = jax.jit(lambda p, xb, yb: [w - 0.5 * g for w, g in zip(p, jax.grad(loss)(p, xb, yb))])
    first = float(loss(params, x, y))
    for _ in range(300):
        params = step(params, x, y)
    last = float(loss(params, x, y))
    acc = float(jnp.mean(jnp.argmax(jnp.tanh(x @ params[0] + params[1]) @ params[2] + params[3], 1) == y))
    print(f"loss {first:.4f} -> {last:.4f}, accuracy {acc:.3f}")
    expect(last < first / 10, f"training did not converge: loss {first:.4f} -> {last:.4f}")
    expect(acc >= 0.98, f"accuracy {acc:.3f} < 0.98")


CHECKS = [import_and_device, float32_ops, float64_ops, linalg, fft_and_convolution, float16, bfloat16, int8,
          prng_golden, gradients, mlp_training]

if __name__ == "__main__":
    if sys.argv[1:] == ["--list"]:
        print(" ".join(c.__name__ for c in CHECKS))
        sys.exit(0)
    {c.__name__: c for c in CHECKS}[sys.argv[1]]()
    print("ok")
