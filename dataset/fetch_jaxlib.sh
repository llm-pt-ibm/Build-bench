#!/bin/bash
# Fetch the sources of the jaxlib build-recipe case: jax 0.10.2 and the XLA
# commit it pins, with the patches jax itself applies to XLA (the same tree an
# upstream x86_64 build compiles). The trees are too large for git and are
# recreated with this script.
# Usage: dataset/fetch_jaxlib.sh [case_dir]   (default data/x86_64_to_ppc64le/jaxlib)
set -euo pipefail
case_dir=${1:-data/x86_64_to_ppc64le/jaxlib}
JAX_TAG=jax-v0.10.2
mkdir -p "$case_dir"
cd "$case_dir"

if [ ! -d jax ]; then
  rm -rf "jax-$JAX_TAG"
  curl -fsSL "https://github.com/jax-ml/jax/archive/refs/tags/$JAX_TAG.tar.gz" | tar xz
  mv "jax-$JAX_TAG" jax
fi
XLA_COMMIT=$(sed -n 's/^XLA_COMMIT = "\(.*\)"/\1/p' jax/third_party/xla/revision.bzl)
if [ ! -d xla ]; then
  rm -rf "xla-$XLA_COMMIT"
  curl -fsSL "https://github.com/openxla/xla/archive/$XLA_COMMIT.tar.gz" | tar xz
  # the patches listed in jax/third_party/xla/workspace.bzl, in order
  for p in $(grep -oE '"//third_party/xla:[^"]+\.patch"' jax/third_party/xla/workspace.bzl | sed 's|"//third_party/xla:||; s|"||'); do
    echo "applying jax's XLA patch $p"
    patch -d "xla-$XLA_COMMIT" -p1 --fuzz=0 -s < "jax/third_party/xla/$p"
  done
  mv "xla-$XLA_COMMIT" xla
fi
echo "jax $JAX_TAG and xla $XLA_COMMIT ready in $case_dir"
du -sh jax xla
