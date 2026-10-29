#!/bin/bash
# Acceptance test of zita-resampler: a program linked against the built
# library resamples a 1 kHz sine from 48 kHz to 44.1 kHz; the output must keep
# the amplitude (RMS 0.7071) and the frequency.
set -uo pipefail
lib=$BENCH_SRC_DIR/zita-resampler/source/libzita-resampler.so.1.11.2
[ -f "$lib" ] || { echo "error: the build left no libzita-resampler.so.1.11.2"; exit 1; }
work=$BENCH_CACHE_DIR/acceptance
rm -rf "$work" && mkdir -p "$work" && cd "$work"
ln -s "$lib" libzita-resampler.so.1
cat > resample.cc <<'EOF'
// resample a 1 kHz sine from 48 kHz to 44.1 kHz; print its RMS and frequency
#include <cmath>
#include <cstdio>
#include <vector>
#include <zita-resampler/resampler.h>
int main() {
    const int n = 48000;
    std::vector<float> in(n), out(n);
    for (int i = 0; i < n; i++) in[i] = std::sin(2 * M_PI * 1000.0 * i / 48000.0);
    Resampler r;
    if (r.setup(48000, 44100, 1, 48)) { std::puts("setup failed"); return 1; }
    r.inp_count = n; r.inp_data = in.data(); r.out_count = n; r.out_data = out.data();
    r.process();
    int got = n - r.out_count;
    double s = 0; int m = 0, cross = 0;
    for (int i = 4000; i < got - 4000; i++) {
        s += out[i] * out[i]; m++;
        if (out[i - 1] < 0 && out[i] >= 0) cross++;
    }
    double rms = std::sqrt(s / m), freq = cross * 44100.0 / m;
    std::printf("samples %d rms %.5f frequency %.1f\n", got, rms, freq);
    return (got > 40000 && std::fabs(rms - M_SQRT1_2) < 1e-3 && std::fabs(freq - 1000) < 2) ? 0 : 1;
}
EOF
"${CXX:-g++}" -O2 -I"$BENCH_SRC_DIR/zita-resampler/source" resample.cc -o resample "$lib" -lpthread \
  || { echo "error: compiling the test program against the library failed"; exit 1; }
LD_LIBRARY_PATH=$work${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} ./resample || { echo "FAIL: the resampled sine is wrong"; exit 1; }
echo "PASS zita-resampler"
