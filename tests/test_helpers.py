import glob
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from tools.auto_repair.patch_check import check_patch_format  # noqa: E402
from tools.auto_repair.log_excerpt import error_excerpt  # noqa: E402

for path in glob.glob("data/**/*.patch", recursive=True):
    if "/testdata/" not in path:
        assert not check_patch_format(open(path, errors="replace").read()), path
assert not check_patch_format("")
assert not check_patch_format("diff --git a/x b/y\nsimilarity index 100%\nrename from x\nrename to y\n")
assert check_patch_format("--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n-a\n+b\n+c\n")
patch = open("data/x86_64_to_ppc64le/zita-resampler/disable-sse.patch").read()
assert check_patch_format(patch.replace("+CPPFLAGS += -DENABLE_NEON\n", ""))
assert check_patch_format("no hunks here\n")
short = "--- a/v.bzl\n+++ b/v.bzl\n@@ -1164,7 +1164,7 @@\n     os = 1,\n-    arch = 1,\n+    arch = 2,\n   ),\n"
assert not check_patch_format(short) and check_patch_format(short, strict=True)
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
bazel_log = ("ERROR: /c/external/rules_python/repo_utils.bzl:83:16: An error occurred during the fetch\n"
             "Error in fail: \nrules_python:host_compatible_python_repo FAIL: Could not find a compatible "
             "'host' python for 'linux', 'ppc64le'\n")
assert "Could not find a compatible" in error_excerpt(bazel_log)
many = "".join(f"ERROR: /c/curl/BUILD:26:11: Compiling lib/f{i}.c failed: (Exit 1): clang failed (from target @@curl//:curl)\n"
               f"/c/boringssl/base.h:124:2: error: \"Unknown target CPU\"\n" for i in range(300))
many += "/c/hwy/targets.cc: undeclared inclusion(s) error: x\nERROR: Build did NOT complete successfully\n"
ex = error_excerpt(many)
assert 'error: "Unknown target CPU" [x300]' in ex and "undeclared inclusion" in ex, ex
assert ex.count("@@curl//:curl") == 1 and "[and 299 more failed actions of this target]" in ex, ex
crash = ("=== check: install the wheel and run a program\n"
         "F1014 14:28:57.030297   48137 ir_compiler.cc:398] Unsupported CPU type: powerpc64le-unknown-linux-gnu\n"
         + "    @     0x7fffa6df6030  xla::cpu::IrCompiler::operator()()\n" * 20
         + "./build.sh: line 42: 47654 Aborted                 (core dumped)\n")
assert "Unsupported CPU type" in error_excerpt(crash), error_excerpt(crash)
from tools.auto_repair.log_excerpt import same_failure  # noqa: E402
original = open("data/x86_64_to_ppc64le/jaxlib/log_failed.txt", errors="replace").read()
moved = original.replace("4ebb03ef3cb1bd622034ef725e8576a1", "0123456789abcdef0123456789abcdef")
corrupted = ("ERROR: /root/obs-worker/script/jaxlib/cache/bazel/4ebb03ef3cb1bd622034ef725e8576a1/external/rules_python/"
             "python/private/pypi/pypi_repo_utils.bzl:112:31: An error occurred during the fetch of repository 'pypi':\n"
             "Error in path: Unable to load package for @@pypi__packaging//:packaging-24.2.dist-info/RECORD\n")
assert same_failure(original, moved) and not same_failure(original, corrupted)
print("log excerpt: OK (with root-cause comparison)")
import json, shutil, tempfile  # noqa: E402
import tools.auto_repair.local_build as local_build  # noqa: E402

work = tempfile.mkdtemp()
fake = os.path.join(work, "fake_build.sh")
with open(fake, "w") as f:
    f.write('#!/bin/bash\n'
            'test -f "$OBS_WORKER_ROOT/rootfs/var/tmp/bench-src/$2/p.spec" || exit 9\n'
            'echo "1/2 (P) foo.rpm"\n'
            'echo "[    0s] ----- building p.spec"\n'
            'if grep -q broken "$OBS_WORKER_ROOT/rootfs/var/tmp/bench-src/$2/p.spec"; then\n'
            '  echo "[    1s] p.c:1:1: error: boom"; echo "[    1s] error: Bad exit status from x (%build)"\n'
            '  echo "Build failed with exit code 1"; exit 1; fi\n'
            'echo ok\n')
os.chmod(fake, 0o755)
local_build.BUILD_SCRIPT = fake
cfg = {"max_wait_seconds": 60, "check_interval": 1,
       "local": {"worker_root": os.path.join(work, "worker"), "project": "P", "repository": "standard",
                 "arch": "ppc64le", "jobs": 1}}
pkg_dir = os.path.join(work, "p")
os.makedirs(pkg_dir)
open(os.path.join(pkg_dir, "log_failed.txt"), "w").write("old")
open(os.path.join(pkg_dir, "p.spec"), "w").write("broken\n")
assert local_build.local_check(pkg_dir, "p", cfg).startswith("Build check error: no upload")
assert local_build.local_upload("p", pkg_dir, cfg).startswith("Success: 1 files staged")
staged = os.listdir(os.path.join(cfg["local"]["worker_root"], "rootfs/var/tmp/bench-src/p"))
assert staged == ["p.spec"], staged
res = local_build.local_check(pkg_dir, "p", cfg)
assert res.startswith("Build failed!") and "error: boom" in res, res
saved = open(os.path.join(pkg_dir, "log_failed.txt")).read()
assert saved.startswith("[    0s] ----- building") and saved.rstrip().endswith("(%build)"), saved
open(os.path.join(pkg_dir, "p.spec"), "w").write("fixed\n")
local_build.local_upload("p", pkg_dir, cfg)
assert local_build.local_check(pkg_dir, "p", cfg).startswith("Build succeeded!")
marker = json.load(open(os.path.join(pkg_dir, ".last_upload.json")))
marker["srcmd5"] = "x"
json.dump(marker, open(os.path.join(pkg_dir, ".last_upload.json"), "w"))
assert "no build was started for the last upload" in local_build.local_check(pkg_dir, "p", cfg)
# network failures before the build: retried, then reported as infrastructure errors
import tools.auto_repair.infra as infra  # noqa: E402
infra.RETRY_WAITS = (0, 0)
flaky = os.path.join(work, "flaky_build.sh")
with open(flaky, "w") as f:
    f.write('#!/bin/bash\nn=$(cat "$OBS_WORKER_ROOT/tries" 2>/dev/null || echo 0); echo $((n+1)) > "$OBS_WORKER_ROOT/tries"\n'
            '[ "$n" -lt "$(cat "$OBS_WORKER_ROOT/fail_times")" ] && { echo "HTTPSConnection: Failed to resolve api.opensuse.org"; exit 1; }\n'
            'echo "[    0s] ----- building p.spec"; echo ok\n')
os.chmod(flaky, 0o755)
local_build.BUILD_SCRIPT = flaky
open(os.path.join(cfg["local"]["worker_root"], "fail_times"), "w").write("2")
local_build.local_upload("p", pkg_dir, cfg)
assert local_build.local_check(pkg_dir, "p", cfg).startswith("Build succeeded!"), "retried after network failures"
os.remove(os.path.join(cfg["local"]["worker_root"], "tries"))
open(os.path.join(cfg["local"]["worker_root"], "fail_times"), "w").write("9")
local_build.local_upload("p", pkg_dir, cfg)
res = local_build.local_check(pkg_dir, "p", cfg)
assert res.startswith("Build infrastructure error!") and "Failed to resolve" in res, res
shutil.rmtree(work)
print("local build backend: OK (with infrastructure retries)")

import tools.auto_repair.script_build as script_build  # noqa: E402
work = tempfile.mkdtemp()
cfg = {"max_wait_seconds": 60, "check_interval": 1, "local": {"arch": "ppc64le"},
       "script": {"stage_root": os.path.join(work, "stage"), "jobs": 2}}
pkg_dir = os.path.join(work, "r")
os.makedirs(os.path.join(pkg_dir, "src"))
open(os.path.join(pkg_dir, "src", "main.c"), "w").write("broken\n")
open(os.path.join(pkg_dir, "build.sh"), "w").write(
    'echo "jobs=$BENCH_JOBS cache=$BENCH_CACHE_DIR shared=$BENCH_SHARED_CACHE_DIR"; touch out.o\n'
    'grep -q broken src/main.c && { echo "$(pwd)/src/main.c:1:1: error: boom"; exit 1; }\nexit 0\n')
res = script_build.script_upload("r", pkg_dir, cfg)
assert res.startswith("Success: sources snapshotted"), res
res = script_build.script_check(pkg_dir, "r", cfg)
assert res.startswith("Build failed!") and f"{pkg_dir}/src/main.c:1:1: error: boom" in res, res
assert "jobs=2" in open(os.path.join(pkg_dir, "log_failed.txt")).read()
assert "/r/shared" in open(os.path.join(pkg_dir, "log_failed.txt")).read()
open(os.path.join(pkg_dir, "src", "main.c"), "w").write("fixed\n")
script_build.script_upload("r", pkg_dir, cfg)
assert script_build.script_check(pkg_dir, "r", cfg).startswith("Build succeeded!")
assert not os.path.exists(os.path.join(pkg_dir, "out.o")), "the build runs on a copy"
# acceptance test of the framework (outside the package): run after a successful build
import tools.auto_repair.acceptance as acceptance  # noqa: E402
acceptance.ACCEPTANCE_DIR = os.path.join(work, "acceptance")
os.makedirs(os.path.join(acceptance.ACCEPTANCE_DIR, "a_to_b"))
with open(os.path.join(acceptance.ACCEPTANCE_DIR, "a_to_b", "r.sh"), "w") as f:
    f.write('grep -q works "$BENCH_SRC_DIR/src/main.c" || { echo "Check failed: the program does not work"; exit 1; }\n')
cfg.update(direction="a_to_b", acceptance_timeout=60)
script_build.script_upload("r", pkg_dir, cfg)
res = script_build.script_check(pkg_dir, "r", cfg)
assert res.startswith("Build failed! The package was built, but its acceptance test failed"), res
assert "Check failed: the program does not work" in res, res
assert "the build succeeded" in open(os.path.join(pkg_dir, "log_failed.txt")).read()
open(os.path.join(pkg_dir, "src", "main.c"), "w").write("fixed, works\n")
script_build.script_upload("r", pkg_dir, cfg)
res = script_build.script_check(pkg_dir, "r", cfg)
assert res == "Build succeeded! The build has been successfully completed and its acceptance test passed.", res
# a cache left inconsistent is removed, with the processes that still use it
import subprocess  # noqa: E402
import time  # noqa: E402
cache = os.path.join(cfg["script"]["stage_root"], "r", "cache")
shared = os.path.join(cfg["script"]["stage_root"], "r", "shared")
open(os.path.join(cache, "stale"), "w").write("x")
open(os.path.join(shared, "content-addressed"), "w").write("x")
child_pid = os.path.join(work, "child.pid")
user = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time; "
                         "open(sys.argv[2], 'w').write(str(subprocess.Popen(['sleep', '60']).pid)); time.sleep(60)",
                         cache, child_pid])
while not os.path.exists(child_pid) or not open(child_pid).read():
    time.sleep(0.1)
script_build.reset_cache("r", cfg)
assert user.wait(timeout=10) != 0 and os.listdir(cache) == [], os.listdir(cache)
assert not os.path.exists(f"/proc/{open(child_pid).read()}/cmdline"), "a child of a cache user survived"
assert os.listdir(shared) == ["content-addressed"], "the shared cache is kept"
shutil.rmtree(work)
print("build-recipe backend: OK (with acceptance test and cache reset)")

# changes made by earlier attempts, for continued runs
from tools.auto_repair.resume import workspace_changes  # noqa: E402
work = tempfile.mkdtemp()
orig, ws = os.path.join(work, "orig"), os.path.join(work, "ws")
os.makedirs(os.path.join(orig, "src"))
open(os.path.join(orig, "src", "a.c"), "w").write("int a;\n")
open(os.path.join(orig, "src", "same.c"), "w").write("x\n")
os.symlink("same.c", os.path.join(orig, "src", "link.c"))
open(os.path.join(orig, "log_failed.txt"), "w").write("log\n")
shutil.copytree(orig, ws)                       # symlinks become files, as in a workspace
open(os.path.join(ws, "src", "a.c"), "w").write("int a = 1;\n")
open(os.path.join(ws, "src", "new.patch"), "w").write("+x\n")
open(os.path.join(ws, "log_failed.txt"), "w").write("other log\n")
changes = workspace_changes(orig, ws)
assert "File: src/a.c" in changes and "+int a = 1;" in changes and "File: src/new.patch" in changes, changes
assert "same.c" not in changes and "link.c" not in changes and "log_failed" not in changes, changes
shutil.rmtree(work)
print("resume: OK (changes against the original package)")

print("\nALL TESTS PASSED")
