#!/bin/bash
# Create the local build worker: an openSUSE Tumbleweed ppc64le chroot with
# osc and obs-build, configured with the OBS account from .env. Packages are
# built with `osc build` against openSUSE:Factory:PowerPC, like on OBS.
# Usage: scripts/local_worker/setup.sh   (run from the repository root)
set -euo pipefail
W=${OBS_WORKER_ROOT:-/root/obs-worker}
PY=${PY:-/root/miniforge3/envs/build_bench/bin/python}
IMAGE=https://download.opensuse.org/ports/ppc/tumbleweed/appliances/opensuse-tumbleweed-image.ppc64le-lxc.tar.xz
here=$(dirname "$0")

grep -E "MemTotal|MemAvailable" /proc/meminfo
if [ ! -x "$W/rootfs/usr/bin/zypper" ]; then
  mkdir -p "$W/rootfs"
  [ -s "$W/rootfs.tar.xz" ] || curl -fsSL --retry 3 "$IMAGE" -o "$W/rootfs.tar.xz"
  # the host may not have xz; decompress with Python
  "$PY" -c "import lzma, shutil, sys; shutil.copyfileobj(lzma.open(sys.argv[1]), open(sys.argv[2], 'wb'))" \
    "$W/rootfs.tar.xz" "$W/rootfs.tar"
  tar -C "$W/rootfs" --numeric-owner -xpf "$W/rootfs.tar"
  rm "$W/rootfs.tar" "$W/rootfs.tar.xz"
fi
"$here/enter.sh" zypper --non-interactive --gpg-auto-import-keys refresh
# osc and obs-build, with the tools obs-build recommends for chroot builds
# (zstd for the OBS preinstall images, hostname, Perl modules); osc runs the
# build through sudo even as root, and needs git
"$here/enter.sh" zypper --non-interactive install --no-recommends osc build obs-service-download_files \
  cpio sudo git-core zstd bsdtar hostname e2fsprogs \
  'perl(Date::Parse)' 'perl(Date::Language)' 'perl(Time::Zone)' 'perl(XML::Parser)' 'perl(YAML::LibYAML)' \
  'perl(Config::IniFiles)' 'perl(LWP::UserAgent)' 'perl(URI)' 'perl(Archive::Tar)' 'perl(Pod::Usage)'

# osc configuration with the account from .env (readable by root only)
mkdir -p "$W/rootfs/root/.config/osc"
"$PY" - "$W/rootfs/root/.config/osc/oscrc" <<'PYEOF'
import os, sys
sys.path.insert(0, os.getcwd())
from tools.auto_repair.obs_config import load_obs_config
c = load_obs_config()
path = sys.argv[1]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(f"[general]\napiurl = {c['api']}\n\n[{c['api']}]\nuser = {c['user']}\npass = {c['password']}\n"
            "credentials_mgr_class = osc.credentials.PlaintextConfigFileCredentialsManager\n")
print(f"osc configured for {c['user']} at {c['api']}")
PYEOF
"$here/enter.sh" osc version
"$here/enter.sh" osc api /about | grep -E "<title>|<revision>"
"$here/enter.sh" ls /usr/lib/build/build
echo "worker ready: $W/rootfs"
