import glob
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from tools.auto_repair.patch_check import check_patch_format  # noqa: E402
from tools.auto_repair.log_excerpt import error_excerpt  # noqa: E402

for path in glob.glob("data/**/*.patch", recursive=True):
    assert not check_patch_format(open(path, errors="replace").read()), path
patch = open("data/x86_64_to_ppc64le/zita-resampler/disable-sse.patch").read()
assert check_patch_format(patch.replace("+CPPFLAGS += -DENABLE_NEON\n", ""))
assert check_patch_format("no hunks here\n")
print("patch check: OK")

log = open("data/x86_64_to_ppc64le/zita-resampler/log_failed.txt", errors="replace").read()
excerpt = error_excerpt(log)
assert "arm_neon.h: No such file or directory" in excerpt and "Bad exit status" in excerpt, excerpt
patch_log = """[   24s] can't open /etc/polkit-1/rules.d/x.rules.new: No such file or directory
[   24s] warning: %post(polkit-default-privs) scriptlet failed, exit status 2
[   28s] Executing(%prep): /usr/bin/bash -e /var/tmp/rpm-tmp.X
[   28s] + echo 'Patch #0 (fix-makefile.patch):'
[   28s] Patch #0 (fix-makefile.patch):
[   28s] patching file source/Makefile
[   28s] + echo 'Patch #1 (disable-sse.patch):'
[   28s] Patch #1 (disable-sse.patch):
[   28s] patching file source/Makefile
[   28s] patch unexpectedly ends in middle of line
[   28s] Hunk #1 FAILED at 33.
[   28s] error: Bad exit status from /var/tmp/rpm-tmp.X (%prep)
[   28s]     Bad exit status from /var/tmp/rpm-tmp.X (%prep)
[   29s] ### VM INTERACTION END ###
"""
excerpt = error_excerpt(patch_log)
assert "polkit" not in excerpt and "VM INTERACTION" not in excerpt, excerpt
for expected in ("Patch #1 (disable-sse.patch)", "unexpectedly ends", "Hunk #1 FAILED"):
    assert expected in excerpt, excerpt
assert "fix-makefile" not in excerpt and excerpt.count("Bad exit status") == 1, excerpt
print("log excerpt: OK")
print("\nALL TESTS PASSED")
