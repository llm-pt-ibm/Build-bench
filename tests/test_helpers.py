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
print("log excerpt: OK")
print("\nALL TESTS PASSED")
