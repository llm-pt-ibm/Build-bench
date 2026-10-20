import asyncio
import atexit
import json
import os
import shutil
import sys
import tempfile

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
# everything the test writes (workspace, results, logs, diff logs) goes to a
# temporary directory, never to the benchmark's own
SCRATCH = tempfile.mkdtemp(prefix="bench_test_offline_")
atexit.register(shutil.rmtree, SCRATCH, ignore_errors=True)
with open(os.environ.get("BENCH_CONFIG", "config/x86_64_to_ppc64le.yaml")) as f:
    config = yaml.safe_load(f)
config["paths"].update({k: os.path.join(SCRATCH, k) for k in ("result_dir", "log_dir", "temp_work_dir")})
config["paths"]["base_dir"] = os.path.join(ROOT, config["paths"]["base_dir"])
with open(os.path.join(SCRATCH, "config.yaml"), "w") as f:
    yaml.safe_dump(config, f)
os.environ["BENCH_CONFIG"] = os.path.join(SCRATCH, "config.yaml")
os.environ["BENCH_DIFF_LOG_DIR"] = os.path.join(SCRATCH, "diff_logs")
os.environ["API_KEY"] = "offline-test"
os.environ["API_BASE_URL"] = "http://127.0.0.1:9/v1"
os.environ["OBS_USER"] = os.environ["OBS_PASSWORD"] = ""
# a read-only build directory (dependency sources of build-recipe cases)
READONLY = os.path.join(SCRATCH, "readonly")
os.makedirs(READONLY, exist_ok=True)
with open(os.path.join(READONLY, "dep.bzl"), "w") as f:
    f.write("cpu = select({'x86': 1})\n")
os.environ["BENCH_READONLY_DIRS"] = READONLY

from openai.types.chat.chat_completion import Choice  # noqa: E402
import client  # noqa: E402

PKG = "zita-resampler"
TMP = os.path.join(SCRATCH, "temp_work_dir", PKG)


def call(i, name, **args):
    return {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


SCRIPT = [
    [call(1, "get_file_content_tool", file_path=f"{TMP}/log_failed.txt"),
     call(2, "get_file_content_tool", file_path=f"{TMP}/zita-resampler.spec")],
    [call(3, "check_build_result", input_dir=TMP, package_name=PKG)],
    [call(4, "get_structure_of_files", package_path=TMP)],
    [call(5, "get_structure_of_files", package_path=TMP)],
    [call(6, "get_structure_of_files", package_path=TMP)],
    [call(7, "get_structure_of_files", package_path=TMP)],
    [call(8, "reset_package_cache_tool", package_name=PKG),
     call(9, "get_file_content", file_path=f"{TMP}/log_failed.txt")],
    None,
]


def validate_conversation(messages):
    i = 0
    while i < len(messages):
        m = messages[i]
        if m["role"] == "assistant" and m.get("tool_calls"):
            ids = {t["id"] for t in m["tool_calls"]}
            got = set()
            j = i + 1
            while j < len(messages) and messages[j]["role"] == "tool":
                got.add(messages[j]["tool_call_id"])
                j += 1
            assert got == ids, f"message {i}: expected responses {ids}, got {got}"
            i = j
        else:
            i += 1


class ScriptedClient(client.AutoRepairClient):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.step = 0
        self.seen = []
        self.script = SCRIPT
        self.reasoning = None

    def _chat(self, messages, tools):
        validate_conversation(messages)
        self.seen = messages
        calls = self.script[self.step]
        self.step += 1
        self.usage["llm_calls"] += 1
        if calls == "EMPTY":
            return Choice.model_validate({"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant", "content": ""}})
        msg = {"role": "assistant", "content": None if calls else "done", "tool_calls": calls}
        if self.reasoning:
            msg["reasoning"] = self.reasoning
        return Choice.model_validate({"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                                      "message": msg})


async def main():
    llm = client.LLMConfig(provider="openai", model="scripted")
    cli = ScriptedClient(llm=llm)
    assert await cli.connect()
    try:
        tools = [t for t in await cli.list_tools_openai_format() if t["function"]["name"] in client.LLM_TOOLS]
        assert sorted(t["function"]["name"] for t in tools) == sorted(client.LLM_TOOLS), tools
        init = json.loads((await cli.session.call_tool("init_package_environment_tool", {
            "base_dir": cli.base_dir, "package_name": PKG,
            "temp_work_dir": cli.temp_work_dir, "result_dir": cli.result_dir})).content[0].text)
        assert init["success"], init
        assert os.path.exists(f"{TMP}/log_failed_original.txt"), "original log not kept"
        cli.usage = {k: 0 for k in ("llm_calls", "tool_calls", "prompt_tokens",
                                    "completion_tokens", "cached_tokens", "cost_usd")}
        cli.timing = {k: 0.0 for k in ("llm_seconds", "upload_seconds",
                                       "build_check_seconds", "other_tool_seconds")}
        cli.dirty = cli.unchecked_upload = False
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "go"}]
        text, ok, summary = await cli._llm_tools_loop(PKG, init["package_path"], messages, tools)
        assert not ok and text == "done"
        assert summary["ended_by"] == "no_tool_calls" and summary["final_check"] is None, summary
        tool_msgs = {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
        validate_conversation(messages)
        assert "arm_neon.h" in tool_msgs["call_1"], "log was not read"
        assert tool_msgs["call_2"].startswith("#"), "spec was not read"
        assert tool_msgs["call_3"].startswith("ERROR: Cannot call check_build_result")
        assert "exceeded max repeat count" in tool_msgs["call_7"], tool_msgs["call_7"][:200]
        for cid in ("call_8", "call_9"):
            assert tool_msgs[cid].startswith("Error: unknown tool"), tool_msgs[cid][:200]
        assert "truncated" not in tool_msgs["call_4"] or len(tool_msgs["call_4"]) < 41000
        print(f"loop: OK ({cli.usage['tool_calls']} tool calls, valid conversation)")

        # an empty reply is retried instead of ending the attempt
        client.EMPTY_REPLY_RETRIES = 2
        cli.script, cli.step = [[call(20, "get_file_content_tool", file_path=f"{TMP}/log_failed.txt")], "EMPTY",
                                [call(21, "get_file_content_tool", file_path=f"{TMP}/zita-resampler.spec")], None], 0
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "go"}]
        text, ok, summary = await cli._llm_tools_loop(PKG, init["package_path"], messages, tools)
        assert summary["ended_by"] == "no_tool_calls" and summary["rounds"] == 2 and summary["empty_replies"] == 1, summary
        assert any("Your last reply was empty" in str(m.get("content")) for m in messages)
        client.EMPTY_REPLY_RETRIES = 0
        print("empty replies: OK (retried, the attempt goes on)")

        # the model's reasoning is saved with its replies but never sent back
        cli.script, cli.step = [[call(22, "get_file_content_tool", file_path=f"{TMP}/log_failed.txt")], None], 0
        cli.reasoning = "the error is in the dependency"
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "go"}]
        await cli._llm_tools_loop(PKG, init["package_path"], messages, tools)
        cli.reasoning = None
        assert messages[2]["reasoning"] == "the error is in the dependency", messages[2]
        assert not any("reasoning" in m for m in client.api_messages(messages))
        assert "dependency" not in cli._notes(messages)
        print("reasoning: OK (kept in the transcript, not sent to the model)")

        # passing provider errors (e.g. rate limits reported as 413) are retried
        import httpx
        import openai
        client.MODEL_RETRY_WAITS = (0, 0)
        calls = []

        def flaky_create(**kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise openai.APIStatusError("rate limit", response=httpx.Response(
                    413, request=httpx.Request("POST", "http://x")), body=None)
            return "reply"
        cli.client = type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {
            "create": staticmethod(flaky_create)})})})()
        assert cli._create_with_retries(model="m") == "reply" and len(calls) == 3
        calls.clear()
        cli.client.chat.completions.create = staticmethod(lambda **kw: (_ for _ in ()).throw(openai.APIStatusError(
            "bad request", response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)))
        try:
            cli._create_with_retries(model="m")
            raise AssertionError("a 400 error must not be retried")
        except openai.APIStatusError as e:
            assert e.status_code == 400
        print("model calls: OK (passing provider errors retried, others raised)")

        cases = {
            "Build result: Build succeeded! The build has been successfully completed.": True,
            "Build result: Build broken! OBS could not process the sources: x": False,
            "Build result: Build failed! The failed log has been updated to: temp_workspace/tokio/log_failed.txt": False,
            "Build result: Build unresolvable! The build can not begin: nothing provides foo": False,
            "Build result: Build timeout! The build has not been completed within 3600 seconds.": False,
        }
        for text_in, expected in cases.items():
            got = json.loads((await cli.session.call_tool("parse_build_result_tool", {
                "result_content": text_in, "package_name": PKG})).content[0].text)["success"]
            assert got == expected, (text_in, got)
        print("parser: OK (only 'Build succeeded!' counts as success)")

        spec = f"{TMP}/zita-resampler.spec"
        old = open(spec, encoding="utf-8").read()
        new = old.replace("%ifnarch x86_64", "%ifarch aarch64", 1)
        assert new != old
        (await cli.session.call_tool("modify_file_tool", {"file_path": spec, "new_content": new}))
        upd = json.loads((await cli.session.call_tool("update_prompt_with_history_tool", {
            "package_name": PKG, "package_path": TMP, "build_attempt": 2,
            "formatted_prompt": "system"})).content[0].text)["messages"][1]["content"]
        assert "File: zita-resampler.spec" in upd and "+%ifarch aarch64" in upd, upd[:500]
        print("history: OK (modify_file_tool feeds the next attempt's prompt)")

        async def tool(name, **args):
            return (await cli.session.call_tool(name, args)).content[0].text

        assert (await tool("get_file_content_tool", file_path="/etc/hostname")).startswith("Error:"), "path guard"
        assert "outside the package workspace" in await tool("modify_file_tool", file_path="client.py", new_content="x")
        assert (await tool("modify_file_tool", file_path=f"{TMP}/new-fix.patch",
                           new_content="--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n-a\n+b\n")).startswith("Success: Created")
        bad = open(f"data/x86_64_to_ppc64le/{PKG}/disable-sse.patch").read().replace("+CPPFLAGS += -DENABLE_NEON\n", "")
        assert "Warning: this patch is malformed" in await tool("modify_file_tool", file_path=f"{TMP}/disable-sse.patch", new_content=bad)
        good = open(f"data/x86_64_to_ppc64le/{PKG}/disable-sse.patch").read()
        assert "final newline was added" in await tool("modify_file_tool", file_path=f"{TMP}/disable-sse.patch",
                                                       new_content=good.rstrip("\n"))
        assert open(f"{TMP}/disable-sse.patch").read() == good, "final newline restored"
        await tool("modify_file_tool", file_path=f"{TMP}/no-eol.txt", new_content="x\n")
        open(f"{TMP}/no-eol.txt", "w").write("x")
        await tool("modify_file_tool", file_path=f"{TMP}/no-eol.txt", new_content="y")
        assert open(f"{TMP}/no-eol.txt").read() == "y", "files without a final newline are kept so"
        assert "belongs to the benchmark framework" in await tool(
            "modify_file_tool", file_path=f"{TMP}/log_failed_original.txt", new_content="x")
        spec_path = f"{TMP}/zita-resampler.spec"
        assert (await tool("replace_in_file_tool", file_path=spec_path, old_text="Name:", new_text="Name: ")
                ).startswith("Success: Replaced 1 occurrence")
        assert "not found" in await tool("replace_in_file_tool", file_path=spec_path, old_text="no such text",
                                         new_text="x")
        assert "occurs" in await tool("replace_in_file_tool", file_path=spec_path, old_text="%", new_text="%")
        assert "outside the package workspace" in await tool("replace_in_file_tool", file_path="client.py",
                                                             old_text="import", new_text="x")
        found = await tool("search_files_tool", path=TMP, pattern="^Name: ", file_glob="*.spec")
        assert found.startswith(f"{TMP}/zita-resampler.spec:"), found
        assert "dep.bzl:1:" in await tool("search_files_tool", path=READONLY, pattern="select")
        assert (await tool("get_file_content_tool", file_path=f"{READONLY}/dep.bzl")).startswith("cpu = ")
        assert (await tool("modify_file_tool", file_path=f"{READONLY}/dep.bzl", new_content="x")).startswith("Error")
        assert (await tool("search_files_tool", path="/etc", pattern="root")).startswith("Error")
        shallow = json.loads(await tool("get_structure_of_files", package_path=os.path.dirname(TMP), max_depth=1))
        assert shallow["structure"][os.path.basename(os.path.dirname(TMP))][PKG].startswith("<"), shallow
        part = await tool("get_file_content_tool", file_path=f"{TMP}/log_failed.txt", start_line=2, max_lines=3)
        assert part.startswith("[lines 2-4 of "), part[:80]
        print("file tools: OK (workspace guard, new files, patch check, final newline, line ranges,"
              " replace, search, read-only build dirs, structure depth)")

        assert (await tool("extract_archive_tool", package_path=TMP)).startswith("Successfully extracted")
        assert (await tool("extract_archive_tool", package_path=TMP)).startswith("Already extracted")
        assert (await tool("compress_to_archive_tool", package_path=TMP)).startswith("No files inside")
        assert (await tool("extract_archive_tool", package_path=TMP)).startswith("Successfully extracted")
        mk = f"{TMP}/extracted/zita-resampler-1.11.2/source/Makefile"
        await tool("modify_file_tool", file_path=mk, new_content=open(mk).read() + "# edited\n")
        assert (await tool("compress_to_archive_tool", package_path=TMP)).startswith("Success: Compressed")
        print("archive tools: OK (no silent re-extraction, unchanged archives kept)")

        up = (await cli.session.call_tool("upload_file_to_obs_tool", {"package_path": TMP})).content[0].text
        assert "credentials missing" in up, up
        print("upload without credentials: OK (explicit error, no OBS call)")
    finally:
        await cli.cleanup()


asyncio.run(main())
print("\nALL TESTS PASSED")
