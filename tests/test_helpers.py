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
indented = "".join(f"FAIL check{i} (exit status 134, aborted)\n    F1015 20:18:0{i}.5 2449{i} ir_compiler.cc:398] "
                   "Unsupported CPU type: powerpc64le-unknown-linux-gnu\n" for i in range(9))
ex = error_excerpt(indented)
assert "Unsupported CPU type" in ex and "[x9]" in ex, ex
from tools.auto_repair.log_excerpt import same_failure  # noqa: E402
from tools.auto_repair.log_excerpt import ACCEPTANCE_MARK, failure_signature  # noqa: E402
_acc = (ACCEPTANCE_MARK + "\nPASS int8\nFAIL jax_test_suite (exit status 1): 20 failed, 1508 passed, 70 skipped "
        "in 164.03s (0:02:44)\nacceptance: 1 check(s) failed\n")
assert failure_signature(_acc) == failure_signature(_acc.replace("164.03s (0:02:44)", "159.71s (0:02:39)"))
assert failure_signature(_acc) != failure_signature(_acc.replace("20 failed, 1508", "18 failed, 1510"))
_tail = "    FAILED tests/nn_test.py::NNFunctionsTest::test{} - worker 'gw{}' crashed\n"
assert failure_signature(_acc.replace("acceptance:", _tail.format(3, 5) + "acceptance:")) == \
    failure_signature(_acc.replace("acceptance:", _tail.format(11, 2) + "acceptance:")), "parallel test order"
_blog = "ERROR: /x/cache/bazel/4ebb03ef3cb1bd62/external/llvm/a.cpp:12:3: error: no member 'f'\nINFO: 12.3s\n"
assert failure_signature(_blog) == failure_signature(_blog.replace("4ebb03ef3cb1bd62", "99aa03ef3cb1bd6f"))
assert failure_signature(_blog) != failure_signature(_blog.replace("'f'", "'g'"))
assert failure_signature("") == ()
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

# run settings (scripts/bench.py)
import importlib.util  # noqa: E402
import tempfile as _tempfile  # noqa: E402
spec = importlib.util.spec_from_file_location("bench", os.path.join(ROOT, "scripts", "bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
with _tempfile.TemporaryDirectory() as tmp:
    profile_path = os.path.join(tmp, "bench.yaml")
    open(profile_path, "w").write("source_arch: x86_64\ntarget_arch: ppc64le\nlabel: r1\npackages: [a, b]\n"
                                  "model: m\nprovider: p\ntemperature:\nllm:\n  max_build_attempts: 12\n")
    p = bench.load_profile(profile_path, {"attempts": "3", "packages": "x,y", "model": None})
    assert p["attempts"] == "3" and p["packages"] == ["x", "y"] and p["model"] == "m" and p["repeats"] == 1, p
    assert p["config"] == profile_path and p["llm"] == {"max_build_attempts": 12}, "the config is the profile"
    os.environ["LLM_TEMPERATURE"] = "0.5"
    env = bench.run_env(p, resume={"from": "r0_1", "workspace": None})
    assert env["BENCH_PACKAGES"] == "x,y" and env["BENCH_MAX_ATTEMPTS"] == "3" and env["LLM_MODEL"] == "m"
    assert env["OPENROUTER_PROVIDER"] == "p" and env["BENCH_RESUME_FROM"] == "r0_1"
    assert env["LLM_TEMPERATURE"] == "" and env["BENCH_RESUME_WORKSPACE"] == "", "unset settings are empty"
    del os.environ["LLM_TEMPERATURE"]
    p = bench.load_profile(profile_path, {"provider": "none", "model": "anthropic/x"})
    assert p["provider"] is None and bench.run_env(p)["OPENROUTER_PROVIDER"] == "", p
    # .env does not fill in what the config leaves empty (load_dotenv keeps what is set)
    from dotenv import load_dotenv as _load_dotenv
    open(os.path.join(tmp, "dotenv"), "w").write("OPENROUTER_PROVIDER=from-dotenv\n")
    _saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(bench.run_env(p))
        _load_dotenv(os.path.join(tmp, "dotenv"))
        assert os.environ["OPENROUTER_PROVIDER"] == "", "PROVIDER=none stays cleared"
    finally:
        os.environ.clear()
        os.environ.update(_saved)
    paths = {k: os.path.join(tmp, k) for k in ("base_dir", "result_dir", "log_dir", "temp_work_dir")}
    for d in paths.values():
        os.makedirs(d)
    os.makedirs(os.path.join(paths["base_dir"], "a"))
    os.makedirs(os.path.join(paths["log_dir"], "r0_1"))
    open(os.path.join(paths["log_dir"], "a.log"), "w").write("x")
    open(os.path.join(paths["result_dir"], "a_result.json"), "w").write("{}")
    assert len(bench.leftovers(paths, ["a"])) == 2, bench.leftovers(paths, ["a"])
    bench.archive(paths, ["a"], "r1_1_stopped")
    assert not bench.leftovers(paths, ["a"])
    assert os.path.isfile(os.path.join(paths["log_dir"], "r1_1_stopped", "a.log"))
    assert os.path.isfile(os.path.join(paths["result_dir"], "r1_1_stopped", "a_result.json"))
    bench.STATE_DIR, bench.ACTIVE = tmp, os.path.join(tmp, "active.json")
    open(bench.ACTIVE, "w").write('{"label": "r1", "pid": 999999999}')
    assert bench.active_run()["alive"] is False, "a dead runner is not an active run"
    frozen = os.path.join(ROOT, bench.frozen_config(profile_path))
    open(profile_path, "a").write("label: r2\n")   # edited for the next run while this one runs
    assert "r2" not in open(frozen).read() and "label: r1" in open(frozen).read()
print("run settings: OK (overrides, environment, leftovers archived, stale lock, config frozen per run)")

# a profile with a model server of its own: the .env key is not sent there
import http.server  # noqa: E402
import threading  # noqa: E402


class _Models(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        data = json.dumps({"data": [{"id": "local-coder"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


_server = http.server.HTTPServer(("127.0.0.1", 0), _Models)
threading.Thread(target=_server.serve_forever, daemon=True).start()
_saved = os.environ.get("API_KEY")
os.environ["API_KEY"] = "secret-of-another-api"
try:
    local = {"packages": [], "model": "local-coder", "base_url": f"http://127.0.0.1:{_server.server_port}/v1"}
    env = bench.run_env(local)
    assert env["API_BASE_URL"] == local["base_url"] and env["API_KEY"] == "none", "the .env key is never sent"
    os.environ["LOCAL_KEY_FOR_TEST"] = "k1"
    assert bench.run_env(dict(local, api_key_env="LOCAL_KEY_FOR_TEST"))["API_KEY"] == "k1"
    bench.check_model_server(local)   # answers and serves the model
    for broken in (dict(local, model="other-model"), dict(local, base_url="http://127.0.0.1:9/v1")):
        try:
            bench.check_model_server(broken)
            raise AssertionError(f"accepted {broken}")
        except SystemExit:
            pass
    assert bench.run_env({"packages": [], "context_chars": 180000})["BENCH_MAX_CONTEXT_CHARS"] == "180000"
finally:
    _server.shutdown()
    os.environ.pop("LOCAL_KEY_FOR_TEST", None)
    if _saved is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = _saved
print("local model profile: OK (own server and key, server and model checked, context size)")

# leak check: built copies of the package within the model's reach
import shutil  # noqa: E402
from tools.auto_repair.leak_check import leak_report  # noqa: E402
with _tempfile.TemporaryDirectory() as tmp:
    case = os.path.join(tmp, "demo-leaktest")
    os.makedirs(case)
    open(os.path.join(case, "build.sh"), "w").write("true\n")
    env = os.path.join(tmp, "env")
    for d in ("lib/python3.12/site-packages/demo_leaktest", "hidden/site-packages/demo_leaktest", "pkgs"):
        os.makedirs(os.path.join(env, d))
    open(os.path.join(env, "pkgs", "demo_leaktest-1.0-py3-none-any.whl"), "w").write("x")
    open(os.path.join(env, "notes.diff"), "w").write("--- a/x\n+++ b/x\n")
    cfg = {"script": {"experiment_paths": [env], "experiment_hide": [os.path.join(env, "hidden")]}}
    found = leak_report(cfg, "demo-leaktest", case)
    assert len(found) == 2, found
    assert any("installed copy" in f and "lib/python3.12" in f for f in found), found
    assert any("built copy" in f and f.endswith(".whl") for f in found), found
    assert not any("/hidden/" in f for f in found), "hidden paths are not reported"
    assert leak_report({"script": {}}, "demo-leaktest", case) == [], "only what the model can read"
print("leak check: OK (installed copies, built packages, hidden paths skipped)")

# where the benchmark keeps its state: BENCH_HOME, not /root
from tools.auto_repair import paths as bench_paths_mod  # noqa: E402
_home = os.environ.pop("BENCH_HOME", None)
try:
    assert bench_paths_mod.bench_home() == os.path.expanduser("~/.local/share/build-bench")
    os.environ["BENCH_HOME"] = "/srv/bench"
    assert bench_paths_mod.env_dir("x") == "/srv/bench/envs/x"
    dirs = bench_paths_mod.build_dirs({})
    assert dirs == {"worker_root": "/srv/bench/obs-worker", "stage_root": "/srv/bench/stage"}, dirs
    dirs = bench_paths_mod.build_dirs({"script": {"stage_root": "${BENCH_HOME}/s"}, "local": {"worker_root": "~/w"}})
    assert dirs["stage_root"] == "/srv/bench/s" and dirs["worker_root"] == os.path.expanduser("~/w"), dirs
finally:
    os.environ.pop("BENCH_HOME", None)
    if _home is not None:
        os.environ["BENCH_HOME"] = _home
print("paths: OK (BENCH_HOME, ~ and ${VARIABLES} in configs)")

# one config: what it does not choose follows from the two architectures
import yaml  # noqa: E402
from tools.auto_repair import bench_config  # noqa: E402
_saved = {k: os.environ.pop(k, None) for k in ("BENCH_OUTPUT_ROOT", "BENCH_CONFIG")}
try:
    assert bench_config.run_paths({"source_arch": "x86_64", "target_arch": "ppc64le"}) == {
        "base_dir": os.path.join(ROOT, "data", "x86_64_to_ppc64le"),
        "temp_work_dir": os.path.join(ROOT, "temp_workspace"),
        "result_dir": os.path.join(ROOT, "result_text_res", "x86_64_to_ppc64le"),
        "log_dir": os.path.join(ROOT, "result_log_res", "x86_64_to_ppc64le")}
    os.environ["BENCH_OUTPUT_ROOT"] = "/srv/out"
    p = bench_config.run_paths({"source_arch": "x86_64", "target_arch": "aarch64", "cases_dir": "data/case_study/x"})
    assert p["base_dir"] == os.path.join(ROOT, "data", "case_study", "x"), p
    assert p["result_dir"] == "/srv/out/result_text_res/x86_64_to_aarch64", p
    assert p["temp_work_dir"] == "/srv/out/temp_workspace", p
    with _tempfile.TemporaryDirectory() as tmp:
        os.environ["BENCH_CONFIG"] = os.path.join(tmp, "c.yaml")
        open(os.environ["BENCH_CONFIG"], "w").write("source_arch: ppc64le\ntarget_arch: x86_64\n")
        from tools.auto_repair.obs_config import load_obs_config
        c = load_obs_config()
        assert (c["direction"], c["repository"], c["arch"], c["local"]["project"]) == \
            ("ppc64le_to_x86_64", "x86_64", "x86_64", "openSUSE:Factory"), c["direction"]
        assert c["project"] == f"home:{c['user']}:build-bench" and c["api"] == "https://api.opensuse.org"
        open(os.environ["BENCH_CONFIG"], "w").write("source_arch: x86_64\ntarget_arch: aarch64\n"
                                                    "obs: {repository: arm, project: 'p:{user}'}\n")
        c = load_obs_config()
        assert (c["repository"], c["local"]["project"], c["project"]) == \
            ("arm", "openSUSE:Factory:ARM", f"p:{c['user']}"), "obs settings override the derived ones"
finally:
    for k, v in _saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v
# the repository has one config, bench.yaml, and its cases exist
repo_cfg = bench_config.load(os.path.join(ROOT, "bench.yaml"))
assert os.path.isdir(bench_config.run_paths(repo_cfg)["base_dir"]), repo_cfg["source_arch"]
assert not glob.glob(os.path.join(ROOT, "config", "*.yaml")), "one config: bench.yaml"
print("config: OK (one file; cases, workspace, results and OBS settings follow from the architectures)")

# build environments: one env.yaml of lists; make setup-env does the rest
import platform  # noqa: E402
from tools.auto_repair import build_env  # noqa: E402
for _name in os.listdir(os.path.join(ROOT, "envs")):
    if os.path.isfile(build_env.spec_file(_name)):
        build_env.load(_name)                     # the repository's environments are valid
_example = build_env.load_file(build_env.EXAMPLE)
_keys = set(_example) | {line.lstrip("# ").split(":")[0] for line in open(build_env.EXAMPLE) if ":" in line}
assert set(build_env.KEYS) <= _keys, set(build_env.KEYS) - _keys   # the example shows every key
with _tempfile.TemporaryDirectory() as tmp:
    _saved_env = {k: os.environ.pop(k, None) for k in ("BENCH_HOME", "CONDA", "BAZEL_BINARY", "WHEELS_FROM")}
    _envs_dir = build_env.ENVS_DIR
    try:
        build_env.ENVS_DIR = os.path.join(tmp, "envs")
        os.makedirs(os.path.join(tmp, "envs", "demo"))
        os.environ["BENCH_HOME"] = os.path.join(tmp, "home")
        open(build_env.spec_file("demo"), "w").write("conda: [python=3.12, clang]\ntools: [openjdk]\n")
        assert build_env.load("demo")["wheels"] == [] and build_env.exists("demo")
        made = build_env.new("demo2")                       # make new-env: the example, to edit
        assert open(made).read() == open(build_env.EXAMPLE).read()
        try:
            build_env.new("demo2")
            raise AssertionError("new-env overwrote an environment")
        except SystemExit as e:
            assert "exists already" in str(e), e
        assert build_env.env_script("demo") == build_env.GENERIC_SCRIPT
        open(build_env.spec_file("demo"), "w").write("system: [zlib-devel]\n")    # any package: no conda needed
        assert build_env.load("demo")["system"] == ["zlib-devel"]
        for bad, why in (("conda: [x]\nwheel: [y]\n", "unknown keys"), ("conda: x\n", "is a list"),
                         ("system: [a]\nwheels: [b]\n", "need a Python"), ("env: [CC]\n", "env maps"),
                         ("channels: []\n", "nothing to set up")):
            open(build_env.spec_file("demo"), "w").write(bad)
            try:
                build_env.load("demo")
                raise AssertionError(bad)
            except SystemExit as e:
                assert why in str(e), e
        # a conda that makes environments with a python, clang, javac and the C++ runtime
        log = os.path.join(tmp, "conda.log")
        conda = os.path.join(tmp, "conda")
        open(conda, "w").write(f"""#!/bin/sh
echo "$*" >> {log}
prefix=; prev=
for a in "$@"; do [ "$prev" = -p ] && prefix=$a; prev=$a; done
case "$1" in
  create) mkdir -p "$prefix/bin" "$prefix/lib"; ln -sf {sys.executable} "$prefix/bin/python"
          printf '#!/bin/sh\\necho "clang version 17.0.6"\\n' > "$prefix/bin/clang"; chmod +x "$prefix/bin/clang"
          touch "$prefix/bin/javac" "$prefix/lib/libstdc++.so.6" "$prefix/lib/libgcc_s.so.1";;
  list) case "$*" in *--json*) echo '[{{"name": "python", "version": "3.12.0"}}]';;
                    *) printf '@EXPLICIT\\nhttps://conda.example/python-3.12.0.conda#0\\n';; esac;;
esac
""")
        os.chmod(conda, 0o755)
        bazel = os.path.join(tmp, "bazel-bin")
        open(bazel, "w").write('#!/bin/sh\necho "bazel 7.7.0"\n')
        os.environ.update(CONDA=conda, BAZEL_BINARY=bazel)
        open(build_env.spec_file("demo"), "w").write(
            "conda: [python=3.12, clang]\ntools: [openjdk]\nbazel: 7.7.0\nenv: {DEMO_VAR: $BENCH_ENV_DIR/x}\n"
            'setup: ["echo run >> setup.log && ln -sf /bin/true bin/demo-tool"]\n')
        d = build_env.setup("demo")
        for f in ("build.lock", "tools.lock"):              # the solution is written, to be committed
            assert "@EXPLICIT" in open(os.path.join(tmp, "envs", "demo", f)).read(), f
        assert os.path.isfile(os.path.join(tmp, "home", "bazel", "7.7.0", "bazel")), "Bazel is shared"
        assert os.access(os.path.join(d, "bin", "bazel-7.7.0"), os.X_OK), "and copied into the environment"
        assert os.path.islink(os.path.join(d, "runtime-lib", "libstdc++.so.6"))
        if platform.machine() in build_env.TRIPLETS:
            assert os.path.islink(os.path.join(d, "bin", build_env.TRIPLETS[platform.machine()] + "-gcc"))
        info = json.load(open(os.path.join(d, "env.json")))
        assert info["name"] == "demo" and info["bazel"]["version"] == "7.7.0" and len(info["id"]) == 12, info
        assert os.path.isfile(os.path.join(d, ".complete")) and os.path.isdir(os.path.join(d, "test"))
        creates = open(log).read().count("create ")
        assert creates == 3, open(log).read()               # build, tools, test
        build_env.setup("demo")
        assert open(log).read().count("create ") == creates, "a second setup skips what is done"
        assert open(os.path.join(d, "setup.log")).read() == "run\n", "setup commands run once"
        # a changed conda list is solved again, and its environments made again
        spec_text = open(build_env.spec_file("demo")).read()
        open(build_env.spec_file("demo"), "w").write(spec_text.replace("[python=3.12, clang]", "[python=3.12, clang, hdf5]"))
        build_env.setup("demo")
        assert open(log).read().count("create ") == creates + 2, "build and test again, tools kept"
        assert "hdf5" in open(os.path.join(tmp, "envs", "demo", "build.lock")).read()
        assert "hdf5" not in open(os.path.join(tmp, "envs", "demo", "tools.lock")).read()
        assert build_env._tool_env(d, {"HDF5_DIR": "$BENCH_ENV_DIR/build"})["HDF5_DIR"] == f"{d}/build"
        # mamba's listing has no @EXPLICIT and names the environment: the lock has only the URLs
        assert build_env._explicit('List of packages in environment: "/x/tools"\n\nhttps://c/a.conda#1\n') == \
            "@EXPLICIT\nhttps://c/a.conda#1\n"
        assert "@EXPLICIT" in open(os.path.join(tmp, "envs", "demo", "build.lock")).read()
        assert 'export DEMO_VAR="$BENCH_ENV_DIR/x"' in open(os.path.join(d, "exports.sh")).read()
        # the generic script exports what the environment has
        out = subprocess.run(["bash", "-c", 'set -u; source "$0" >/dev/null && echo "${PYTHON:-}|${TEST_PYTHON:-}|'
                              '${CLANG:-}|${BAZEL:-}|${JAVA_HOME:-}|${LOCAL_WHEELS:-}|${DEMO_VAR:-}|'
                              '$(command -v demo-tool)"', build_env.GENERIC_SCRIPT],
                             env=dict(os.environ, BENCH_ENV_DIR=d), capture_output=True, text=True)
        assert out.stdout.strip() == "|".join([f"{d}/build/bin/python", f"{d}/test/bin/python",
                                               f"{d}/build/bin/clang", f"{d}/bin/bazel-7.7.0", f"{d}/tools",
                                               "", f"{d}/x", f"{d}/bin/demo-tool"]), (out.stdout, out.stderr)
        # the image: the default Containerfile, with the RHEL packages of system
        from tools.auto_repair import container as _ctr
        _default = open(os.path.join(ROOT, "envs", "Containerfile")).read()
        assert _ctr.containerfile("demo") == _default
        _text = _ctr.containerfile("demo", ["zlib-devel", "openssl-devel"])
        assert _text.startswith(_default) and "--nodocs zlib-devel openssl-devel" in _text, _text
        os.remove(os.path.join(d, ".complete"))
        out = subprocess.run(["bash", "-c", 'source "$0"', build_env.GENERIC_SCRIPT],
                             env=dict(os.environ, BENCH_ENV_DIR=d), capture_output=True, text=True)
        assert out.returncode == 1 and "make setup-env ENV=demo" in out.stdout, out.stdout
        # wheels: one at a time, the built ones kept, a failure's errors shown
        wd = os.path.join(tmp, "wheels")
        os.makedirs(wd)
        open(os.path.join(wd, "ml_dtypes-0.5.1-cp312-cp312-linux_ppc64le.whl"), "w").close()
        assert build_env._built_wheel(wd, "ml-dtypes==0.5.1") and not build_env._built_wheel(wd, "ml-dtypes==0.5.4")
        assert build_env._built_wheel(wd, "ml_dtypes") and not build_env._built_wheel(wd, "numpy==2.1.3")
        open(os.path.join(tmp, "w.log"), "w").write(
            "Collecting x\n  aes_gcm.cc:12:5: error: unknown type name 'foo'\n  aes_gcm.cc:12:5: error: unknown "
            "type name 'foo'\nnote: This error originates from a subprocess\nERROR: Failed building wheel for x\n")
        assert build_env._error_lines(os.path.join(tmp, "w.log")) == [
            "aes_gcm.cc:12:5: error: unknown type name 'foo'", "ERROR: Failed building wheel for x"]
        # an environment script of its own replaces the generic one
        open(os.path.join(tmp, "envs", "demo.sh"), "w").write("true\n")
        assert build_env.env_script("demo") == os.path.join(tmp, "envs", "demo.sh")
    finally:
        build_env.ENVS_DIR = _envs_dir
        for k, v in _saved_env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
print("build environments: OK (env.yaml from the example, any package: system, env, setup; locks written, "
      "Bazel shared, setup skips what is done, generic script)")

# the build environment of a case is checked for leaks too
with _tempfile.TemporaryDirectory() as tmp:
    os.environ["BENCH_HOME"] = tmp
    try:
        case = os.path.join(tmp, "demo-leaktest")
        os.makedirs(case)
        open(os.path.join(case, "build.sh"), "w").write("true\n")
        json.dump({"environment": "demo-env"}, open(os.path.join(case, "manifest.json"), "w"))
        os.makedirs(os.path.join(tmp, "envs", "demo-env", "build", "lib", "python3.12", "site-packages",
                                 "demo_leaktest"))
        found = leak_report({"script": {}}, "demo-leaktest", case)
        assert len(found) == 1 and "envs/demo-env/build" in found[0], found
    finally:
        os.environ.pop("BENCH_HOME", None)
print("leak check: OK (the case's build environment)")

# a new case from the template, and what check_case says about it
sys.path.insert(0, os.path.join(ROOT, "dataset"))
from new_case import new_case, fetch_case, source_dir_name, version_of  # noqa: E402
from check_case import check_case  # noqa: E402
assert source_dir_name("https://github.com/tensorflow/tensorflow/archive/refs/tags/v2.20.0.tar.gz") == "tensorflow"
assert source_dir_name("https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.bz2") == "eigen"
assert source_dir_name("https://www.zlib.net/zlib-1.3.1.tar.xz") == "zlib"
assert version_of("https://github.com/tensorflow/tensorflow/archive/refs/tags/v2.20.0.tar.gz") == "2.20.0"
assert version_of("https://github.com/openxla/xla/archive/5a9e73cbd925.tar.gz") == ""
with _tempfile.TemporaryDirectory() as tmp:
    data_dir = os.path.join(tmp, "testsrc_to_ppc64le")
    test_dir = os.path.join(ROOT, "acceptance", "testsrc_to_ppc64le")
    _envs_dir = build_env.ENVS_DIR
    try:
        made = new_case(data_dir, "demo", "jax-power9")       # no sources, an environment that exists
        created = made["created"]
        assert len(created) == 3 and os.access(created[0], os.X_OK) and not made["env_created"], made
        failures = [m for level, m in check_case(os.path.join(data_dir, "demo"), {"script": {}}) if level == "FAIL"]
        assert len(failures) == 2 and "no sources" in failures[0] and "log_failed.txt" in failures[1], failures
        os.makedirs(os.path.join(data_dir, "demo", "src"))
        open(os.path.join(data_dir, "demo", "log_failed.txt"), "w").write("error: x\n" * 100)
        results = check_case(os.path.join(data_dir, "demo"), {"script": {}})
        assert not [m for level, m in results if level == "FAIL"], results
        assert sum(level == "WARN" for level, _ in results) == 2, results   # TODOs left in build.sh and test
        # SOURCE: the archive unpacked, its build system's build.sh, test and new environment
        build_env.ENVS_DIR = os.path.join(tmp, "envs")
        os.makedirs(os.path.join(tmp, "src", "lib-1.2"))
        open(os.path.join(tmp, "src", "lib-1.2", "CMakeLists.txt"), "w").write("project(lib)\n")
        subprocess.run(["tar", "czf", "lib-1.2.tar.gz", "lib-1.2"], cwd=os.path.join(tmp, "src"), check=True)
        url = "file://" + os.path.join(tmp, "src", "lib-1.2.tar.gz")
        made = new_case(data_dir, "lib", "", [url])
        case_dir = os.path.join(data_dir, "lib")
        assert made["system"] == "CMake" and made["env_created"] and made["environment"] == "lib", made
        assert os.path.isfile(os.path.join(case_dir, "lib", "CMakeLists.txt"))
        assert "cd lib\ncmake -S . -B build" in open(os.path.join(case_dir, "build.sh")).read()
        assert "ctest --test-dir" in open(os.path.join(test_dir, "lib.sh")).read()
        assert open(os.path.join(case_dir, ".gitignore")).read().splitlines()[-1] == "/lib/"
        manifest = json.load(open(os.path.join(case_dir, "manifest.json")))
        assert manifest["task"]["sources"] == {"lib": url} and manifest["task"]["version"] == "1.2", manifest
        assert build_env.load("lib")["conda"] == ["cxx-compiler", "cmake", "make"]
        shutil.rmtree(os.path.join(case_dir, "lib"))                  # make fetch: the sources again
        fetch_case(case_dir)
        assert os.path.isfile(os.path.join(case_dir, "lib", "CMakeLists.txt"))
        ok = [m for level, m in check_case(case_dir, {"script": {}}) if level == "OK"]
        assert any(m == "sources: lib" for m in ok), ok                 # .gitignore is not a source
    finally:
        build_env.ENVS_DIR = _envs_dir
        shutil.rmtree(test_dir, ignore_errors=True)
print("cases: OK (new case from an archive and its build system, check_case finds what is missing)")

# experiments run sandboxed (needs root and unshare, as on the Power9 build host)
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from tools.auto_repair.experiment import run_experiment  # noqa: E402

if os.geteuid() == 0 and shutil.which("unshare") and \
        subprocess.run(["unshare", "--mount", "true"], capture_output=True).returncode == 0:
    tmp = tempfile.mkdtemp(dir=ROOT, prefix=".test_experiment_")
    try:
        workspace = os.path.join(tmp, "work", "demo")
        os.makedirs(workspace)
        open(os.path.join(workspace, "build.sh"), "w").write("true\n")
        tool_dir = os.path.join(tmp, "toolchain")
        os.makedirs(os.path.join(tool_dir, "secret"))
        open(os.path.join(tool_dir, "tool.txt"), "w").write("toolchain\n")
        open(os.path.join(tool_dir, "secret", "answer.txt"), "w").write("solution\n")
        cfg = {"script": {"stage_root": os.path.join(tmp, "stage"), "jobs": 2, "experiment_paths": [tool_dir],
                          "experiment_hide": [os.path.join(tool_dir, "secret")]}}
        os.makedirs(os.path.join(tmp, "stage", "demo", "cache"))
        open(os.path.join(tmp, "stage", "demo", "cache", "dep.txt"), "w").write("dependency\n")
        out = run_experiment("demo", workspace, " ; ".join([
            "echo hello > note.txt && cat note.txt",
            "cat $BENCH_CACHE_DIR/dep.txt",
            f"cat {tool_dir}/tool.txt; cat {tool_dir}/secret/answer.txt 2>/dev/null || echo hidden",
            "touch $BENCH_WORKSPACE/x 2>&1 | grep -o 'Read-only file system'",
            "touch $BENCH_CACHE_DIR/x 2>&1 | grep -o 'Read-only file system'",
            f"ls {ROOT}/MODIFICATIONS.md 2>&1 | grep -o 'No such file'",
            "umount /root 2>&1 | grep -o 'must be superuser'",
            "(exec 3<>/dev/tcp/1.1.1.1/53) 2>&1 | grep -o 'Network is unreachable'",
            "exit 3"]), 60, cfg)
        assert out.startswith("Command exit status 3"), out
        assert "solution" not in out, out
        for expected in ("hello", "dependency", "toolchain\nhidden", "Read-only file system\nRead-only file system",
                         "No such file", "must be superuser", "Network is unreachable"):
            assert expected in out, (expected, out)
        assert open(os.path.join(tmp, "stage", "demo", "scratch", "note.txt")).read() == "hello\n"
        assert not os.path.exists(os.path.join(workspace, "x"))
        assert "timed out after 2 s" in run_experiment("demo", workspace, "sleep 30", 2, cfg)
        # stopping a run stops its experiments too
        import threading  # noqa: E402
        from tools.auto_repair.script_build import stop_experiments  # noqa: E402
        outcome, started = {}, time.time()
        worker = threading.Thread(target=lambda: outcome.update(
            out=run_experiment("demo", workspace, "sleep 60", 120, cfg)))
        worker.start()
        time.sleep(3)
        stop_experiments("demo", cfg)
        worker.join(30)
        assert not worker.is_alive() and time.time() - started < 30, "experiment not stopped"
        assert "exit status -9" in outcome["out"] or "exit status 137" in outcome["out"], outcome["out"][:200]
        # the case's build environment (make setup-env) is there, read-only, with BENCH_ENV_DIR
        env_script = os.path.join(ROOT, "envs", "demo-test-env.sh")
        os.environ["BENCH_HOME"] = os.path.join(tmp, "home")
        try:
            os.makedirs(os.path.join(tmp, "home", "envs", "demo-test-env"))
            open(os.path.join(tmp, "home", "envs", "demo-test-env", "tool"), "w").write("env tool\n")
            open(env_script, "w").write('export DEMO_TOOL="$BENCH_ENV_DIR/tool"\n')
            json.dump({"environment": "demo-test-env"}, open(os.path.join(workspace, "manifest.json"), "w"))
            out = run_experiment("demo", workspace,
                                 'cat "$DEMO_TOOL"; touch "$BENCH_ENV_DIR/x" 2>&1 | grep -o "Read-only"', 60, cfg)
            assert "env tool" in out and "Read-only" in out, out
        finally:
            os.environ.pop("BENCH_HOME", None)
            if os.path.exists(env_script):
                os.remove(env_script)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("experiments: OK (sandbox hides /root, read-only package, cache and build environment, no network)")
else:
    print("experiments: skipped (needs root and unshare)")

# experiments in a container (Podman, else Docker), with the base image of the
# environments' images (BENCH_TEST_IMAGE: another one with bash)
from tools.auto_repair import container as container_mod  # noqa: E402
# runtime auto: podman if it is installed, else docker
_available, _rt = container_mod.available, os.environ.pop("BENCH_CONTAINER_RUNTIME", None)
try:
    container_mod.available = lambda name: name == "docker"
    assert container_mod.settings({})["runtime"] == "docker"
    container_mod.available = lambda name: True
    assert container_mod.settings({"container": {"runtime": "auto"}})["runtime"] == "podman"
    assert container_mod.settings({"container": {"runtime": "docker"}})["runtime"] == "docker"
finally:
    container_mod.available = _available
    if _rt is not None:
        os.environ["BENCH_CONTAINER_RUNTIME"] = _rt
# the user, unknown to the image's /etc/passwd under docker run --user, is
# named by USER (Bazel stops without it) and gets a HOME it can write
_argv = container_mod.command({"container": {"runtime": "docker"}}, "x", "demo", [], {"HOME": "/s"}, "/", ["true"])
assert f"USER={container_mod.user_name()}" in _argv and "HOME=/s" in _argv and "HOME=/tmp" not in _argv, _argv
assert "HOME=/tmp" in container_mod.command({"container": {"runtime": "docker"}}, "x", "demo", [], {}, "/", ["true"])
_image = os.getenv("BENCH_TEST_IMAGE", "registry.access.redhat.com/ubi8/ubi:8.9")
_runtime = next((rt for rt in ("podman", "docker") if shutil.which(rt) and subprocess.run(
    [rt, "image", "inspect", _image], capture_output=True, env=container_mod.runtime_env()).returncode == 0), None)
if _runtime:
    tmp = tempfile.mkdtemp(dir=ROOT, prefix=".test_container_")
    env_script = os.path.join(ROOT, "envs", "demo-ctr-env.sh")
    os.environ["BENCH_HOME"] = os.path.join(tmp, "home")
    subprocess.run([_runtime, "tag", _image, "build-bench-demo-ctr-env"], check=True, env=container_mod.runtime_env())
    try:
        workspace = os.path.join(tmp, "work", "demo")
        os.makedirs(workspace)
        open(os.path.join(workspace, "build.sh"), "w").write("true\n")
        cfg = {"container": {"runtime": _runtime},
               "script": {"stage_root": os.path.join(tmp, "stage"), "jobs": 2}}
        assert "no build environment" in run_experiment("demo", workspace, "true", 60, cfg)
        # no limit of processes beyond the host's (Podman's 2048 broke jaxlib's test suite)
        argv = container_mod.command(cfg, "x", "demo-ctr-env", [], {}, "/", ["true"])
        assert argv[argv.index("--pids-limit") + 1] == "-1", argv
        # builds need no list of hosts (any host, logged); commands have no network
        assert container_mod.check(cfg, "demo-ctr-env") is None
        json.dump({"environment": "demo-ctr-env"}, open(os.path.join(workspace, "manifest.json"), "w"))
        os.makedirs(os.path.join(tmp, "home", "envs", "demo-ctr-env"))
        open(os.path.join(tmp, "home", "envs", "demo-ctr-env", "tool"), "w").write("env tool\n")
        open(env_script, "w").write('export DEMO_TOOL="$BENCH_ENV_DIR/tool"\n')
        tool_dir = os.path.join(tmp, "toolchain")
        os.makedirs(os.path.join(tool_dir, "secret"))
        open(os.path.join(tool_dir, "tool.txt"), "w").write("toolchain\n")
        open(os.path.join(tool_dir, "secret", "answer.txt"), "w").write("solution\n")
        cfg["script"].update(experiment_paths=[tool_dir], experiment_hide=[os.path.join(tool_dir, "secret")])
        os.makedirs(os.path.join(tmp, "stage", "demo", "cache"), exist_ok=True)
        open(os.path.join(tmp, "stage", "demo", "cache", "dep.txt"), "w").write("dependency\n")
        os.chmod(tmp, 0o755)   # Docker runs the container as the user, its daemon as root
        out = run_experiment("demo", workspace, " ; ".join([
            "echo hello > note.txt && cat note.txt",
            "cat $BENCH_CACHE_DIR/dep.txt",
            'cat "$DEMO_TOOL"',
            f"cat {tool_dir}/tool.txt",
            f"cat {tool_dir}/secret/answer.txt 2>/dev/null || echo hidden",
            "touch $BENCH_WORKSPACE/x 2>/dev/null || echo read-only",
            'touch "$BENCH_ENV_DIR/x" 2>/dev/null || echo read-only',
            f"ls {ROOT}/MODIFICATIONS.md 2>/dev/null || echo no-framework",
            "mount -t tmpfs none /mnt 2>/dev/null || echo no-mount",
            "(exec 3<>/dev/tcp/1.1.1.1/53) 2>/dev/null || echo no-network",
            "exit 3"]), 120, cfg)
        assert out.startswith("Command exit status 3"), out
        assert "hello\ndependency\nenv tool\ntoolchain\nhidden\nread-only\nread-only\nno-framework\n" \
               "no-mount\nno-network\n" in out, out
        assert open(os.path.join(tmp, "stage", "demo", "scratch", "note.txt")).read() == "hello\n"
        assert "timed out after 3 s" in run_experiment("demo", workspace, "sleep 60", 3, cfg)
        left = subprocess.run([_runtime, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True,
                              env=container_mod.runtime_env()).stdout
        assert "bench-demo-exp" not in left, left
        # a build reaches any host, through the framework's proxy, which logs
        # every connection (needs a Python in the image for the forwarder)
        if subprocess.run([_runtime, "run", "--rm", "--network", "none", "build-bench-demo-ctr-env", "sh", "-c",
                           "command -v python3 || test -x /usr/libexec/platform-python"],
                          capture_output=True, env=container_mod.runtime_env()).returncode == 0:
            import http.server as _hs
            import socket as _socket
            import threading as _threading

            class _Served(_hs.BaseHTTPRequestHandler):
                def log_message(self, *a):
                    pass

                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Length", "6")
                    self.end_headers()
                    self.wfile.write(b"served")

            with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as _s:
                _s.connect(("10.255.255.255", 1))           # the host's address, as the proxy reaches it
                _ip = _s.getsockname()[0]
            _origin = _hs.HTTPServer((_ip, 0), _Served)
            _threading.Thread(target=_origin.serve_forever, daemon=True).start()
            _get = ('exec 3<>/dev/tcp/127.0.0.1/3128 && printf "GET http://%s/ HTTP/1.0\\r\\n\\r\\n" >&3 '
                    '&& cat <&3; exec 3<&-')
            # (the proxy's answer for a host it cannot reach names the DNS
            # failure, which counts as a failure of the network, not of the
            # package: it stays out of the log, the network log records it)
            open(os.path.join(workspace, "build.sh"), "w").write(
                f"{_get % f'{_ip}:{_origin.server_port}'}\necho\n{{ {_get % 'answers.example'}; }} >/dev/null\n"
                "(exec 4<>/dev/tcp/1.1.1.1/53) 2>/dev/null || echo no-direct-network\nexit 1\n")
            bcfg = dict(cfg, max_wait_seconds=120, check_interval=1, local={"arch": "ppc64le"},
                        container={"runtime": _runtime, "build_network": "log"})
            try:
                res = script_build.script_upload("demo", workspace, bcfg)
                assert res.startswith("Success"), res
                res = script_build.script_check(workspace, "demo", bcfg)
            finally:
                _origin.shutdown()
            assert res.startswith("Build failed!"), res
            log = open(os.path.join(workspace, "log_failed.txt")).read()
            assert "served" in log and "no-direct-network" in log, log
            net = container_mod.network_log(os.path.join(tmp, "stage", "demo", "run"))
            assert net == {"reached": [f"{_ip}:{_origin.server_port}"], "failed": ["answers.example:80"]}, net
            print("  builds in a container: any host through the proxy, every connection logged, no direct network")
    finally:
        subprocess.run([_runtime, "rmi", "build-bench-demo-ctr-env"], capture_output=True,
                       env=container_mod.runtime_env())
        os.environ.pop("BENCH_HOME", None)
        if os.path.exists(env_script):
            os.remove(env_script)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"experiments in a container: OK ({_runtime}: only the mounts, hidden paths, no capabilities, "
          "no network, timeout)")
else:
    print("experiments in a container: skipped (needs podman or docker with the base image)")

# tool calls a model wrote as text (tools/auto_repair/text_tool_calls.py)
from tools.auto_repair.text_tool_calls import parse as parse_text_calls  # noqa: E402
_tools = [{"type": "function", "function": {"name": "run_command_tool", "parameters": {"properties": {
    "command": {"type": "string"}, "timeout_seconds": {"type": "integer"}}}}}]
_cmd = {"name": "run_command_tool", "arguments": {"command": "ls"}}
for _text, _rest in [
        ('Look.\n<tool_call>\n{"name": "run_command_tool", "arguments": {"command": "ls"}}\n</tool_call>', "Look."),
        ("<tool_call>\n<function=run_command_tool>\n<parameter=command>\nls\n</parameter>\n</function>\n</tool_call>",
         ""),
        ("<tool_call>run_command_tool\n<arg_key>command</arg_key>\n<arg_value>ls</arg_value>\n</tool_call>", ""),
        ('[TOOL_CALLS][{"name": "run_command_tool", "arguments": {"command": "ls"}}]', ""),
        ('[TOOL_CALLS]run_command_tool[ARGS]{"command": "ls"}', ""),
        ('<|python_tag|>{"name": "run_command_tool", "parameters": {"command": "ls"}}', ""),
        ("<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>run_command_tool\n```json\n"
         '{"command": "ls"}\n```<｜tool▁call▁end｜><｜tool▁calls▁end｜>', ""),
        ('<｜tool▁call▁begin｜>run_command_tool<｜tool▁sep｜>{"command": "ls"}<｜tool▁call▁end｜>', ""),
        ('<|channel|>commentary to=functions.run_command_tool <|constrain|>json<|message|>{"command": "ls"}<|call|>',
         ""),
        ('```json\n{"name": "run_command_tool", "arguments": {"command": "ls"}}\n```', "")]:
    assert parse_text_calls(_text, _tools) == ([_cmd], _rest), (_text, parse_text_calls(_text, _tools))
assert parse_text_calls("<function=run_command_tool><parameter=timeout_seconds>60</parameter></function>",
                        _tools)[0][0]["arguments"] == {"timeout_seconds": 60}
for _text in ('The call would be {"name": "run_command_tool", "arguments": {"command": "ls"}} but I stop.',
              '<tool_call>{"name": "other_tool", "arguments": {}}</tool_call>', "Done: the build passed.", ""):
    assert parse_text_calls(_text, _tools)[0] == [], _text
print("text tool calls: OK (Hermes/Qwen, Qwen3-Coder, GLM, Mistral, Llama, DeepSeek, gpt-oss, bare JSON; "
      "prose and unknown tools left alone)")

# the build's network: the proxy lets a build reach any host and logs every
# connection; proxy_forward.py makes its socket a TCP proxy
import http.server  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402


class _Origin(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "6")
        self.end_headers()
        self.wfile.write(b"origin")


_origin = http.server.HTTPServer(("127.0.0.1", 0), _Origin)
threading.Thread(target=_origin.serve_forever, daemon=True).start()
_port = _origin.server_port
_tmp = tempfile.mkdtemp(prefix="bench_net_")
_sock, _log, _fport = os.path.join(_tmp, "p.sock"), os.path.join(_tmp, "network.log"), 0
with socket.socket() as _s:
    _s.bind(("127.0.0.1", 0))
    _fport = _s.getsockname()[1]
_proxy = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "auto_repair", "net_proxy.py"),
                           "--socket", _sock, "--log", _log])
try:
    for _ in range(50):
        if os.path.exists(_sock):
            break
        time.sleep(0.1)
    _forward = subprocess.Popen([sys.executable, os.path.join(ROOT, "scripts", "script_worker", "proxy_forward.py"),
                                 _sock, str(_fport)], stdout=subprocess.PIPE, text=True)
    assert _forward.stdout.readline().strip() == "ready"

    def _ask(request: bytes) -> bytes:
        with socket.create_connection(("127.0.0.1", _fport), timeout=10) as c:
            c.sendall(request)
            data = b""
            while True:
                chunk = c.recv(65536)
                if not chunk:
                    return data
                data += chunk
                if request.startswith(b"CONNECT") and b"\r\n\r\n" in data and b"origin" not in data:
                    c.sendall(b"GET / HTTP/1.0\r\n\r\n")
                    request = b""

    assert _ask(f"GET http://127.0.0.1:{_port}/x HTTP/1.1\r\nHost: x\r\n\r\n".encode()).endswith(b"origin")
    assert _ask(f"GET http://localhost:{_port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode()).endswith(b"origin")
    _tunnel = _ask(f"CONNECT 127.0.0.1:{_port} HTTP/1.1\r\n\r\n".encode())
    assert _tunnel.startswith(b"HTTP/1.1 200 Connection established") and _tunnel.endswith(b"origin"), _tunnel
    assert b" 502 " in _ask(b"CONNECT 127.0.0.1:1 HTTP/1.1\r\n\r\n")    # nothing listens there
    _forward.kill()
finally:
    _proxy.kill()
    _proxy.wait()
    _origin.shutdown()
_lines = [line.split(maxsplit=1)[1].strip() for line in open(_log)]
assert _lines == [f"reached GET 127.0.0.1:{_port}/x", f"reached GET localhost:{_port}/",
                  f"reached CONNECT 127.0.0.1:{_port}", "failed CONNECT 127.0.0.1:1"], _lines
from tools.auto_repair.container import network_log  # noqa: E402
assert network_log(_tmp) == {"reached": [f"127.0.0.1:{_port}", f"localhost:{_port}"], "failed": ["127.0.0.1:1"]}
shutil.rmtree(_tmp, ignore_errors=True)
print("build network: OK (any host, through the socket and the forwarder, every connection logged)")

print("\nALL TESTS PASSED")
