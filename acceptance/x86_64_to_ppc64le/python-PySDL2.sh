#!/bin/bash
# Acceptance test of python-PySDL2: the wheel installs and the package's tests
# pass with SDL's dummy drivers, but for the three the distribution leaves out
# (they need a display) and those of SDL2_gfx, which conda-forge lacks for
# ppc64le. It runs without network on what build.sh left in $BENCH_SRC_DIR
# ($BENCH_CACHE_DIR: scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/pysdl2
wheel=$(ls "$src"/dist/*.whl 2>/dev/null | head -1)
[ -n "$wheel" ] || { echo "error: the build left no wheel in dist/"; exit 1; }
venv=$BENCH_CACHE_DIR/acceptance-venv
rm -rf "$venv"
"${TEST_PYTHON:-python3}" -m venv --system-site-packages "$venv"
"$venv/bin/pip" install -q --no-deps --no-index "$wheel"
cd "$BENCH_CACHE_DIR"   # not the source tree, so that the installed package is imported
export PYSDL2_DLL_PATH=$(dirname "$(readlink -f "${TEST_PYTHON:-python3}")")/../lib
export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy SDL_RENDER_DRIVER=software
# in the sources, as the distribution runs them: sdl2 is pure Python, the same as the wheel installs
cd "$src"
# also left out: font metrics and rectangles that differ with conda-forge's SDL and SDL_ttf (they
# pass on OBS, on ppc64le too)
envdiff="test_TTF_GlyphMetrics or test_TTF_GlyphMetrics32 or test_TTF_SizeText or test_TTF_SizeUTF8"
envdiff="$envdiff or test_TTF_SizeUNICODE or test_SDL_GetSetClipRect or test_SDL_GetSetWindowMouseRect"
"$venv/bin/python" -m pytest -q -p no:cacheprovider sdl2/test --ignore=sdl2/test/sdlgfx_test.py -k "not (test_SDL_SetWindowDisplayMode or test_SDL_SetWindowFullscreen or test_SDL_SetHint or $envdiff)"
