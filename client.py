import asyncio
import subprocess
import sys
import os
import json
import time
import traceback
from typing import Dict, List, Optional, Tuple
from contextlib import AsyncExitStack
import yaml
from dotenv import load_dotenv
import openai
from openai import OpenAI
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters
from tools.auto_repair import container
from tools.auto_repair.acceptance import ACCEPTANCE_DIR, acceptance_test
from tools.auto_repair.case_type import case_environment, case_type
from tools.auto_repair.leak_check import leak_report
from tools.auto_repair.log_excerpt import failure_signature, same_failure
from tools.auto_repair.script_build import reset_cache
from tools.auto_repair.resume import workspace_changes
from tools.auto_repair.text_tool_calls import parse as parse_text_tool_calls
from tools.auto_repair.obs_config import load_obs_config
from tools.auto_repair.paths import env_dir

load_dotenv(".env")
CONFIG_PATH = os.getenv("BENCH_CONFIG", "config/info.yaml")
with open(CONFIG_PATH, "r") as f:
    info = yaml.safe_load(f)
TOOL_TIMEOUT = int(info.get("obs", {}).get("max_wait_seconds", 3600)) + 300
OPENROUTER_PROVIDER = os.getenv("OPENROUTER_PROVIDER")
# Optional comma-separated list of packages to run (default: every package)
BENCH_PACKAGES = {p.strip() for p in os.getenv("BENCH_PACKAGES", "").split(",") if p.strip()}
LLM_TEMPERATURE = float(os.environ["LLM_TEMPERATURE"]) if os.getenv("LLM_TEMPERATURE") else None


class LLMConfig:
    """
    Unified config so we can swap providers/models without changing client logic.

    Priority for credentials per provider:
      - OPENAI_* for native OpenAI (e.g., gpt-5-mini)
      - DASHSCOPE_* for Qwen (DashScope)
      - CHATANYWHERE_* for Claude (OpenAI-compatible facade)

    You can also override via explicit arguments when constructing AutoRepairClientUnified.
    """

    def __init__(
        self,
        provider: str,  # "openai", "qwen", or "claude"
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.provider = provider.lower()
        self.model = model

        if api_key and base_url:
            self.api_key = api_key
            self.base_url = base_url
        else:
            self.api_key = os.getenv("API_KEY")
            self.base_url = os.getenv("API_BASE_URL")

        if not self.api_key and is_local_url(self.base_url):
            self.api_key = "none"   # local model servers (Ollama, vLLM, llama.cpp) need no key
        if not self.api_key:
            raise RuntimeError(
                f"Missing API key for provider={self.provider}. Check your environment.")

    def make_client(self) -> OpenAI:
        # local models can take long for a reply: LLM_TIMEOUT or llm.request_timeout (seconds)
        timeout = float(os.getenv("LLM_TIMEOUT") or LLM_CFG.get("request_timeout", 600))
        if self.base_url:
            return OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)
        return OpenAI(api_key=self.api_key, timeout=timeout)


def is_local_url(url: Optional[str]) -> bool:
    """A model server on this machine or the local network."""
    import ipaddress
    from urllib.parse import urlparse
    host = (urlparse(url or "").hostname or "").lower()
    if host in ("localhost",) or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or address.is_private
    except ValueError:
        return False


def api_base(url: Optional[str]) -> Optional[str]:
    """scheme://host[:port] of the model API, without path or credentials."""
    from urllib.parse import urlparse
    if not url:
        return None
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")


# No tool result is cached: the files change while the agent works, so a cached
# structure listing would go stale after an extraction or an edit.
CACHEABLE_TOOLS = set()

# Repair tools the LLM may call (the agent tools described in the Build-bench
# paper). The other server tools are bookkeeping used only by this client.
LLM_TOOLS = (
    "get_structure_of_files",
    "get_file_content_tool",
    "extract_archive_tool",
    "modify_file_tool",
    "compress_to_archive_tool",
    "upload_file_to_obs_tool",
    "check_build_result",
)
# Extensions for large code bases, enabled in the config (llm.extra_tools):
# search_files_tool and replace_in_file_tool.
LLM_CFG = info.get("llm") or {}
SCRIPT_CFG = (info.get("build") or {}).get("script") or {}
LLM_TOOLS = LLM_TOOLS + tuple(LLM_CFG.get("extra_tools") or ())
# Prompt template per case type (tools/auto_repair/case_type.py)
PROMPTS = {"rpm": "prompts/full_file_generation.txt", "recipe": "prompts/build_recipe_generation.txt",
           **(info.get("prompts") or {})}
# When the conversation grows past this many characters, the oldest tool
# results are shortened (0: never). The last ones are always kept whole.
# BENCH_MAX_CONTEXT_CHARS overrides it for a run, e.g. to fit the context
# window of a local model server.
MAX_CONTEXT_CHARS = int(os.getenv("BENCH_MAX_CONTEXT_CHARS") or LLM_CFG.get("max_context_chars", 0))
# With repeat_guard_per_build, identical calls are counted per build: each
# build result starts a new count, so upload, check and reading the new log
# can be repeated in every repair cycle, while loops without a new build are
# still blocked. Without it, identical calls are counted per attempt.
REPEAT_GUARD_PER_BUILD = bool(LLM_CFG.get("repeat_guard_per_build", False))
# When this many rounds are left in an attempt (0: never), the framework tells
# the model, so that it applies its fix before the attempt ends.
_notice = LLM_CFG.get("round_notice_at", 0)
ROUND_NOTICE_AT = sorted({int(n) for n in (_notice if isinstance(_notice, list) else [_notice]) if int(n) > 0})
# The next attempt's prompt carries up to this many characters of the model's
# own notes (its text replies) from the previous attempt (0: none), so that
# what it found out is not lost when it made no edit.
CARRY_NOTES_CHARS = int(LLM_CFG.get("carry_notes_chars", 0))
# After this many rounds in a row without a change to the package or a build
# (0: never), the framework tells the model to test its hypothesis with a
# change and a build, and an attempt that follows one without any change
# starts with that advice: a model can spend whole attempts reading and
# running experiments (run30: three attempts without a build).
BUILD_DROUGHT_ROUNDS = int(LLM_CFG.get("build_drought_rounds", 0))
# Tell the model when a build failed the same way as the previous one (same
# errors, or same failing checks and tests): the change made since then did
# not affect the failure (run30: two builds with the same 20 failing tests).
REPEATED_FAILURE_NOTE = bool(LLM_CFG.get("repeated_failure_note", False))
# A reply with neither text nor tool calls is a glitch of the model or the
# provider, not a decision to stop: ask the model to continue, at most this
# many times per attempt (0: such a reply ends the attempt, as in the paper).
EMPTY_REPLY_RETRIES = int(LLM_CFG.get("empty_reply_retries", 0))
INFRA_ERROR = "Build result: Build infrastructure error!"
# Continue an earlier run (its label, e.g. run26_flash_6att_1): keep the
# package workspace (optionally copied from BENCH_RESUME_WORKSPACE) and the
# build cache, number the attempts after the earlier ones, and tell the model
# what the earlier attempts changed. BENCH_MAX_ATTEMPTS sets how many more.
RESUME_FROM = os.getenv("BENCH_RESUME_FROM")
RESUME_WORKSPACE = os.getenv("BENCH_RESUME_WORKSPACE")
# Model calls that fail for a passing reason (rate limits, which some
# providers report as 413, unavailable servers, timeouts, dropped connections)
# are retried after these waits, in seconds; if the provider still fails, the
# package's run stops as an infrastructure failure instead of using up attempts.
MODEL_RETRY_WAITS = tuple(LLM_CFG.get("retry_waits", (20, 60, 120, 300, 600)))
# Prompt caching (llm.prompt_cache, BENCH_PROMPT_CACHE): Claude models read a
# cached prefix of the conversation only up to the breakpoints a request marks
# (cache_control), while DeepSeek, OpenAI and Gemini models cache by
# themselves. auto: mark them for Claude models; on: for every model; off.
PROMPT_CACHE = (os.getenv("BENCH_PROMPT_CACHE") or str(LLM_CFG.get("prompt_cache", "auto"))).lower()
# Tool calls a model wrote as text, as models do when the server's tool parser
# does not know their format (llm.text_tool_calls, BENCH_TEXT_TOOL_CALLS):
# a reply without tool calls is searched for them
# (tools/auto_repair/text_tool_calls.py).
TEXT_TOOL_CALLS = (os.getenv("BENCH_TEXT_TOOL_CALLS") or str(LLM_CFG.get("text_tool_calls", True))).lower() \
    not in ("0", "false", "off", "no")
RETRYABLE_STATUS = {408, 409, 413, 429, 500, 502, 503, 504}
KEEP_RECENT_TOOL_RESULTS = int(LLM_CFG.get("keep_recent_tool_results", 8))


def run_metadata(max_build_attempts: int, max_tool_rounds: int) -> Dict:
    def git(*args):
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    status = git("status", "--porcelain", "--untracked-files=no")
    return {
        "git_commit": git("rev-parse", "--short", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_uncommitted_changes": bool(status) if status is not None else None,
        "config": CONFIG_PATH,
        "max_build_attempts": max_build_attempts,
        "max_tool_rounds": max_tool_rounds,
        "final_newline": os.getenv("BENCH_FINAL_NEWLINE", "add").lower(),
        "llm_tools": list(LLM_TOOLS),
        "max_context_chars": MAX_CONTEXT_CHARS,
        "repeat_guard_per_build": REPEAT_GUARD_PER_BUILD,
        "round_notice_at": ROUND_NOTICE_AT,
        "carry_notes_chars": CARRY_NOTES_CHARS,
        "build_drought_rounds": BUILD_DROUGHT_ROUNDS,
        "repeated_failure_note": REPEATED_FAILURE_NOTE,
        "empty_reply_retries": EMPTY_REPLY_RETRIES,
        "model_retry_waits": list(MODEL_RETRY_WAITS),
        "build_backend": (os.getenv("BENCH_BUILD_BACKEND") or (info.get("build") or {}).get("backend", "obs")).lower(),
        # where the model ran: an API such as OpenRouter, or a local server
        "api_base": api_base(os.getenv("API_BASE_URL")),
        "local_model": is_local_url(os.getenv("API_BASE_URL")),
        "prompt_cache": PROMPT_CACHE,
        "text_tool_calls": TEXT_TOOL_CALLS,
    }


def prompt_cache_on(model: str) -> bool:
    if PROMPT_CACHE in ("on", "true", "1", "yes"):
        return True
    if PROMPT_CACHE in ("off", "false", "0", "no"):
        return False
    model = (model or "").lower()
    return model.startswith(("anthropic/", "claude"))


def with_cache_breakpoints(messages: List[Dict]) -> List[Dict]:
    """Mark cache breakpoints (Anthropic allows four): the system prompt, the
    last user or tool message, and the last one before the latest reply. The
    next request then reads the conversation up to its previous end from the
    cache, and writes the new part."""
    out = [dict(m) for m in messages]
    last_reply = max((i for i, m in enumerate(out) if m.get("role") == "assistant"), default=-1)
    inputs = [i for i, m in enumerate(out) if m.get("role") in ("user", "tool")]
    before_reply = [i for i in inputs if i < last_reply]
    marks = {i for i, m in enumerate(out[:1]) if m.get("role") == "system"}
    marks |= set(inputs[-1:]) | set(before_reply[-1:])
    for i in marks:
        content = out[i].get("content")
        if isinstance(content, str) and content:
            out[i]["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
        elif isinstance(content, list) and content:
            parts = [dict(p) for p in content]
            parts[-1]["cache_control"] = {"type": "ephemeral"}
            out[i]["content"] = parts
    return out


def message_reasoning(message) -> str:
    """The model's reasoning behind a reply, when the provider returns it
    (OpenRouter: `reasoning`; DeepSeek's own API: `reasoning_content`)."""
    extra = message.model_extra or {}
    return extra.get("reasoning") or extra.get("reasoning_content") or ""


def api_messages(messages: List[Dict]) -> List[Dict]:
    """The conversation as sent to the model: the reasoning is kept in the
    saved transcripts only, so the model sees what it saw before."""
    return [{k: v for k, v in m.items() if k != "reasoning"} for m in messages]


def make_args_key(tool_name: str, tool_args: dict) -> str:
    return f"{tool_name}::{json.dumps(tool_args, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"


class AutoRepairClient:
    """
    - Connects to MCP server
    - Lists tools (OpenAI function-call format)
    - Iterates packages; for each package, performs N build attempts
    - Within each attempt, runs an LLM<->Tools loop handling tool calls
    - Features from both originals:
        * repeat-call guard + caching of tool results
        * upload-before-check-build enforcement
        * final verification: edits or uploads the model left unchecked are built
    """

    def __init__(
        self,
        llm: Optional[LLMConfig] = None,
        base_dir: Optional[str] = None,
        server_script: str = "server.py",
        max_retries: int = 2,
        max_build_attempts: int = 3,
        max_tool_rounds: int = 20,
    ) -> None:
        self.exit_stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None
        self.is_session_active = False

        # LLM adapter
        self.llm_cfg = llm
        self.client = self.llm_cfg.make_client()
        self.prompt_cache = prompt_cache_on(self.llm_cfg.model)

        # Paths (choose sensible default if not given)
        
        self.base_dir = base_dir or info["paths"]["base_dir"]
        self.result_dir = info["paths"]["result_dir"]
        self.log_dir = info["paths"]["log_dir"]
        self.temp_work_dir = info["paths"]["temp_work_dir"]

        os.makedirs(self.result_dir, exist_ok=True)
        os.makedirs(self.temp_work_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        # the MCP server limits its file tools to this directory, and lets the
        # model read the build caches of the packages of this run (not the
        # whole stage root, which may hold other builds, e.g. a reference fix)
        os.environ["BENCH_TEMP_DIR"] = self.temp_work_dir
        stage_root = self.stage_root = load_obs_config()["script"]["stage_root"]
        packages = sorted(BENCH_PACKAGES or (os.listdir(self.base_dir) if os.path.isdir(self.base_dir) else []))
        os.environ.setdefault("BENCH_READONLY_DIRS", os.pathsep.join(
            [os.path.join(stage_root, p, "cache") for p in packages] + [ACCEPTANCE_DIR]))

        self.server_script = server_script
        self.max_retries = max_retries
        self.max_build_attempts = max_build_attempts
        self.max_tool_rounds = max_tool_rounds

        # Per-package state
        self.upload_status: Dict[str, bool] = {}
        self.attempt = 0

    def _log(self, tag: str, msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(self.log_dir, f"{tag}.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
        print(msg)

    async def connect(self, attempt: int = 1) -> bool:
        self._log("global", f"Connecting to MCP server... (attempt {attempt})")
        try:
            params = StdioServerParameters(
                command=sys.executable, args=[self.server_script],
                env=dict(os.environ),
            )
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(params)
            )
            stdio, write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(stdio, write)
            )
            await self.session.initialize()
            self.is_session_active = True
            self._log("global", "Connected to MCP server.")
            return True
        except Exception as e:
            self._log("global", f"Connect failed: {e}")
            if attempt < self.max_retries:
                await asyncio.sleep(3)
                return await self.connect(attempt + 1)
            return False

    async def list_tools_openai_format(self) -> List[Dict]:
        assert self.session is not None
        resp = await self.session.list_tools()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.inputSchema,
                    "input_schema": t.inputSchema,
                },
            }
            for t in resp.tools
        ]
        return tools

    async def process_all_packages(self):
        if not self.is_session_active and not await self.connect():
            self._log("global", "Cannot connect to MCP server, exit.")
            return

        assert self.session is not None
        # Query server for packages to process
        pkg_resp = await self.session.call_tool(
            "get_packages_to_process",
            {"base_dir": self.base_dir, "result_dir": self.result_dir},
        )
        pkg_info = json.loads(pkg_resp.content[0].text)
        if not pkg_info.get("success"):
            self._log("global", f"Get packages failed: {pkg_info.get('message')}")
            return

        packages = pkg_info.get("packages", [])
        if BENCH_PACKAGES:
            packages = [p for p in packages if p in BENCH_PACKAGES]
        self._log("global", f"Found {len(packages)} packages.")

        tools = await self.list_tools_openai_format()
        tools = [t for t in tools if t["function"]["name"] in LLM_TOOLS]

        for idx, pkg in enumerate(packages, 1):
            self._log("global", f"\n=== [{idx}/{len(packages)}] {pkg} ===")
            try:
                await self.process_one_package(pkg, tools)
            except Exception as e:
                self._log(pkg, f"Fatal error: {e}\n{traceback.format_exc()}")

    async def process_one_package(self, package_name: str, tools: List[Dict]):
        assert self.session is not None

        # Reset upload status for hard dependency enforcement
        self.upload_status[package_name] = False
        self.package = package_name

        resumed = self._resume_state(package_name)
        if resumed and RESUME_WORKSPACE:
            import shutil
            work = os.path.join(self.temp_work_dir, package_name)
            shutil.rmtree(work, ignore_errors=True)
            shutil.copytree(RESUME_WORKSPACE, work, symlinks=True)

        # Initialize temp env (copy package -> temp dir)
        init_ret = await self.session.call_tool(
            "init_package_environment_tool",
            {
                "base_dir": self.base_dir,
                "package_name": package_name,
                "temp_work_dir": self.temp_work_dir,
                "result_dir": self.result_dir,
                "keep_workspace": bool(resumed),
            },
        )
        init_data = json.loads(init_ret.content[0].text)
        if not init_data.get("success"):
            self._log(package_name, f"Init failed: {init_data.get('message')}")
            return

        package_path = init_data["package_path"]
        result_file = init_data["result_file"]
        # the failure the next build is compared with: the original package's
        self.package_path = package_path
        self.changes = 0
        self.last_failure_note = ""
        try:
            with open(os.path.join(package_path, "log_failed_original.txt"), encoding="utf-8",
                      errors="replace") as f:
                self.last_failure = (failure_signature(f.read()), "the original package")
        except OSError:
            self.last_failure = None

        # Load the system prompt template for this kind of case
        kind = case_type(package_path)
        with open(PROMPTS[kind], "r", encoding="utf-8") as f:
            system_prompt_tpl = f.read()
        readonly_dirs = os.path.join(load_obs_config()["script"]["stage_root"], package_name, "cache")
        test = acceptance_test(load_obs_config(), package_name)
        if test:
            system_prompt_tpl += (
                "\n\n## Acceptance test\n"
                f"After every successful build the framework runs the acceptance test `{test}` to check that "
                "the built software installs and works correctly on {target_arch}; a failing test is reported "
                "as a failed build, with the test output as the log. You can read the test, but not change it. "
                "The repair is complete only when the build succeeds and the test passes.")
        if kind == "recipe" and "run_command_tool" in LLM_TOOLS:
            system_prompt_tpl += (
                "\n\n## Experiments\n"
                "`run_command_tool(package_name, command, timeout_seconds)` runs shell commands on the build "
                "host, in the build environment, in seconds instead of a full build: use it to test a hypothesis "
                "before changing the package, e.g. run a single failing test against the last build's artifacts "
                "(in $BENCH_SRC_DIR, and what the acceptance test left in $BENCH_CACHE_DIR), or compile and run "
                "a small program that reproduces a compiler or library bug. The package, $BENCH_SRC_DIR and "
                "$BENCH_CACHE_DIR are read-only there and there is no network; the working directory "
                "$BENCH_SCRATCH_DIR is writable. Changes to the package are still made with the edit tools "
                "and checked with a build.")

        build_succeeded = False
        final_text = ""
        success_attempt = None
        self.usage = {"llm_calls": 0, "tool_calls": 0, "prompt_tokens": 0,
                      "completion_tokens": 0, "cached_tokens": 0, "cache_write_tokens": 0,
                      "text_tool_calls": 0, "cost_usd": 0.0}
        # hosts the package's builds reached and were refused (build_network proxy)
        self.network = {"reached": set(), "refused": set()}
        self.timing = {"llm_seconds": 0.0, "upload_seconds": 0.0,
                       "build_check_seconds": 0.0, "other_tool_seconds": 0.0}
        self.dirty = False            # files changed since the last upload
        self.unchecked_upload = False  # an upload whose build was never checked
        if kind == "recipe" and SCRIPT_CFG.get("build_original_on_init", False) and not resumed:
            await self._build_original(package_name, package_path)
        attempts = []
        notes = resumed["notes"] if resumed else ""
        first = resumed["attempts"] + 1 if resumed else 1
        last = first + self.max_build_attempts - 1
        infrastructure_error = False
        verified_by = None
        t0 = time.time()
        # the code and config this package runs with (not those found when it ends)
        run_info = run_metadata(self.max_build_attempts, self.max_tool_rounds)
        # the answer within the model's reach (scripts/bench.py refuses to start then)
        leaks = leak_report(load_obs_config(), package_name, os.path.join(self.base_dir, package_name))
        # the build environment of a build-recipe case: name and id (make setup-env
        # writes env.json), and the container its builds run in
        environment = None
        if kind == "recipe" and case_environment(package_path):
            name = case_environment(package_path)
            try:
                with open(os.path.join(env_dir(name), "env.json")) as f:
                    env_info = json.load(f)
            except (OSError, ValueError):
                env_info = {}
            environment = {"name": name, "id": env_info.get("id"), "dir": env_dir(name)}
            build_cfg = load_obs_config()
            if container.runtime(build_cfg):
                c = build_cfg["container"]
                environment["container"] = {
                    "runtime": c["runtime"], "image": container.image(name),
                    "image_id": container.image_id(build_cfg, name),
                    "image_base": (env_info.get("image") or {}).get("base"),
                    "image_packages_sha256": (env_info.get("image") or {}).get("packages_sha256"),
                    "build_network": c["build_network"],
                    "allowed_hosts": container.allowed_hosts(build_cfg, name) if c["build_network"] == "proxy"
                    else None}
                recorded = ((env_info.get("image") or {}).get("id") or "").removeprefix("sha256:")
                if recorded and environment["container"]["image_id"] != recorded:
                    self._log(package_name, f"[environment] warning: image {container.image(name)} is not the "
                                            "one make setup-env built (env.json); run make setup-env again")
        for leak in leaks:
            self._log(package_name, f"[leak check] warning: {leak}")

        # Multiple build attempts
        for attempt in range(first, last + 1):
            self.attempt = attempt
            self._log(
                package_name,
                f"--- Build attempt {attempt}/{last} ---",
            )
            try:
                await self.session.call_tool(
                    "reset_package_cache_tool", {"package_name": package_name}
                )
            except Exception as e:
                self._log(package_name, f"Cache clear failed on attempt {attempt}: {e}")

            upd = await self.session.call_tool(
                "update_prompt_with_history_tool",
                {
                    "package_name": package_name,
                    "package_path": package_path,
                    "build_attempt": attempt,
                    "formatted_prompt": system_prompt_tpl.format(
                        package_name=package_name,
                        file_name=result_file,
                        temp_dir=package_path,
                        source_arch=info["source_arch"],
                        target_arch=info["target_arch"],
                        build_wait_minutes=int(info.get("obs", {}).get("max_wait_seconds", 3600)) // 60,
                        build_cache_dir=readonly_dirs,
                        max_tool_rounds=self.max_tool_rounds,
                    ),
                },
            )
            messages = json.loads(upd.content[0].text)["messages"]

            # Ensure the first message is a system message for OpenAI-chat format
            if messages and messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": system_prompt_tpl})
            if resumed and attempt == first and len(messages) > 1 and messages[1].get("role") == "user":
                messages[1]["content"] += (
                    f"\n\n## Earlier attempts\nThis run continues an earlier one: {resumed['attempts']} attempts "
                    "were already made and the package already contains their changes, shown here "
                    "against the original package:\n\n" + (resumed["changes"] or "(no changes)"))
            if BUILD_DROUGHT_ROUNDS and attempts and not attempts[-1].get("builds") \
                    and len(messages) > 1 and messages[1].get("role") == "user":
                messages[1]["content"] += (
                    "\n\n## Note from the framework\nThe previous attempt ended without any change to the "
                    "package or build: all its rounds went to reading and experiments. In this attempt, apply "
                    "the change your findings point to early and build it; the build result tells you more "
                    "than further reading.")
            if notes and len(messages) > 1 and messages[1].get("role") == "user":
                messages[1]["content"] += (
                    "\n\n## Your notes from the previous attempt\n"
                    "What you wrote while working in the previous attempt (the files may have "
                    "changed since):\n" + notes)

            content, ok, summary = await self._llm_tools_loop(
                package_name, package_path, messages, tools
            )
            attempts.append({"attempt": attempt, **summary})
            self._save_transcript(package_name, attempt, messages)
            notes = self._notes(messages)
            if summary.get("ended_by") in ("infrastructure_error", "model_error"):
                infrastructure_error = "build host" if summary["ended_by"] == "infrastructure_error" else "model provider"
                final_text = f"Stopped on attempt {attempt}: the {infrastructure_error} failed (not the package)."
            elif ok:
                verified_by = summary["verified_by"]
                build_succeeded = True
                success_attempt = attempt
                final_text = f"Build succeeded on attempt {attempt}.\n{content or ''}"
            else:
                final_text = f"Build failed on attempt {attempt}.\n{content or ''}"
            finished = bool(infrastructure_error) or build_succeeded or attempt == last
            # after every attempt: a run stopped later can then be continued
            # from its last finished attempt (BENCH_RESUME_FROM)
            with open(result_file, "w", encoding="utf-8") as f:
                f.write(final_text)
            with open(os.path.splitext(result_file)[0] + ".json", "w", encoding="utf-8") as f:
                json.dump({"package": package_name, "model": self.llm_cfg.model,
                           "provider_pinned": OPENROUTER_PROVIDER,
                           "temperature": LLM_TEMPERATURE,
                           "direction": f"{info['source_arch']}_to_{info['target_arch']}",
                           "complete": finished,
                           "success": build_succeeded, "success_attempt": success_attempt,
                           "infrastructure_error": infrastructure_error,
                           "resumed_from": RESUME_FROM,
                           "previous_attempts": resumed["attempts"] if resumed else 0,
                           "success_verified_by": verified_by,
                           "leak_check": leaks,
                           "environment": environment,
                           "network": {k: sorted(v) for k, v in self.network.items()} if self.network["reached"]
                           or self.network["refused"] else None,
                           "minutes": round((time.time() - t0) / 60, 2), **self.usage,
                           "timing": {k: round(v, 1) for k, v in self.timing.items()},
                           "attempts": attempts,
                           "run": run_info},
                          f, indent=2)
            if finished:
                break

        self._log(package_name, f"Final saved to {result_file} | usage: {json.dumps(self.usage)}")
        if not build_succeeded:
            self._log(package_name, "Max attempts reached without success.")

    def _resume_state(self, package_name: str):
        """What a continued run needs from the earlier one: its number of
        attempts, the model's notes of its last attempt and the changes made to
        the package so far (None when not continuing a run)."""
        if not RESUME_FROM:
            return None
        with open(os.path.join(self.result_dir, RESUME_FROM, f"{package_name}_result.json")) as f:
            earlier = json.load(f)
        # the earlier run may itself continue another one
        done = int(earlier.get("previous_attempts") or 0) + len(earlier["attempts"])
        notes = ""
        try:
            with open(os.path.join(self.log_dir, RESUME_FROM, f"{package_name}_attempt{done}_messages.json")) as f:
                notes = self._notes(json.load(f))
        except (OSError, ValueError):
            pass
        work = RESUME_WORKSPACE or os.path.join(self.temp_work_dir, package_name)
        changes = workspace_changes(os.path.join(self.base_dir, package_name), work)
        self._log(package_name, f"Continuing {RESUME_FROM} after {done} attempts")
        return {"attempts": done, "notes": notes, "changes": changes}

    async def _build_original(self, package_name: str, package_path: str) -> None:
        """Start the run from a clean per-run build cache and build the package
        as it is, so that the cache (and the dependency sources the model can
        read there) reflects the original package and nothing an earlier run
        did. The build must fail as the case's original failure; otherwise the
        case or its environment changed, and the run log says so."""
        def original_failure():
            try:
                with open(os.path.join(package_path, "log_failed_original.txt"), errors="replace") as f:
                    return f.read()
            except OSError:
                return ""

        async def build():
            await self._call("upload_file_to_obs_tool", {"package_path": package_path}, "upload_seconds")
            ret = await self._call("check_build_result", {"input_dir": package_path, "package_name": package_name},
                                   "build_check_seconds")
            self._log(package_name, f"[init] build of the original package: {ret.splitlines()[0] if ret else ret}")
            try:
                with open(os.path.join(package_path, "log_failed.txt"), errors="replace") as f:
                    return ret, f.read()
            except OSError:
                return ret, ""

        reset_cache(package_name, load_obs_config())
        self._log(package_name, "[init] per-run build cache cleared")
        ret, log = await build()
        original = original_failure()
        if original and not ("Build failed!" in ret and same_failure(original, log)):
            self._log(package_name, "[init] warning: the original package does not fail as the case's original "
                                    "failure; the case or its build environment changed")

    @staticmethod
    def _notes(messages: List[Dict]) -> str:
        """The model's own text replies of an attempt, latest kept first when
        they exceed CARRY_NOTES_CHARS."""
        if CARRY_NOTES_CHARS <= 0:
            return ""
        texts, seen = [], set()
        for m in messages[2:]:
            text = (m.get("content") or "").strip() if m.get("role") == "assistant" else ""
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        kept, size = [], 0
        for text in reversed(texts):
            if size + len(text) > CARRY_NOTES_CHARS:
                break
            kept.insert(0, text)
            size += len(text)
        return "\n".join(f"- {t}" for t in kept)

    @staticmethod
    def _compact(messages: List[Dict], target: int = 0) -> None:
        """Shorten the oldest tool results when the conversation is longer than
        MAX_CONTEXT_CHARS, down to target characters (MAX_CONTEXT_CHARS when
        0); the last KEEP_RECENT_TOOL_RESULTS stay whole."""
        if MAX_CONTEXT_CHARS <= 0:
            return
        size = sum(len(str(m.get("content") or "")) + len(json.dumps(m.get("tool_calls") or ""))
                   for m in messages)
        if size <= MAX_CONTEXT_CHARS:
            return
        tools_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        for i in tools_idx[:-KEEP_RECENT_TOOL_RESULTS] if KEEP_RECENT_TOOL_RESULTS else tools_idx:
            if size <= (target or MAX_CONTEXT_CHARS):
                break
            content = str(messages[i].get("content") or "")
            if content.startswith("[older tool result shortened") or len(content) < 600:
                continue
            short = (f"[older tool result shortened to save context; it had {len(content)} characters. "
                     f"Call the tool again if you need it.]\n{content[:400]}")
            messages[i]["content"] = short
            size -= len(content) - len(short)

    def _chat(self, messages: List[Dict], tools: List[Dict]):
        # with a prompt cache, shorten well below the limit at once: each
        # shortening changes the conversation's prefix, which the cache holds
        self._compact(messages, int(MAX_CONTEXT_CHARS * 0.8) if self.prompt_cache else 0)
        kwargs = {}
        if LLM_TEMPERATURE is not None:
            kwargs["temperature"] = LLM_TEMPERATURE
        if "openrouter.ai" in (self.llm_cfg.base_url or ""):
            kwargs["extra_body"] = {"usage": {"include": True}}
            if OPENROUTER_PROVIDER:
                kwargs["extra_body"]["provider"] = {"order": [OPENROUTER_PROVIDER], "allow_fallbacks": False}
        started = time.time()
        try:
            sent = api_messages(messages)
            if self.prompt_cache:
                sent = with_cache_breakpoints(sent)
            resp = self._create_with_retries(model=self.llm_cfg.model, messages=sent, tools=tools,
                                             tool_choice="auto", **kwargs)
        finally:
            self.timing["llm_seconds"] += time.time() - started
        u = resp.usage
        self.usage["llm_calls"] += 1
        if u is not None:
            self.usage["prompt_tokens"] += u.prompt_tokens or 0
            self.usage["completion_tokens"] += u.completion_tokens or 0
            details = getattr(u, "prompt_tokens_details", None)
            self.usage["cached_tokens"] += (getattr(details, "cached_tokens", 0) or 0) if details else 0
            # OpenRouter: prompt_tokens_details.cache_write_tokens
            self.usage["cache_write_tokens"] += (
                (getattr(details, "cache_write_tokens", None) or (details.model_extra or {}).get("cache_write_tokens")
                 or 0) if details else 0)
            self.usage["cost_usd"] += float((u.model_extra or {}).get("cost") or 0)
        served = (resp.model_extra or {}).get("provider") or "unknown"
        providers = self.usage.setdefault("providers", {})
        providers[served] = providers.get(served, 0) + 1
        self._write_status(messages)
        choice = resp.choices[0]
        if TEXT_TOOL_CALLS and not choice.message.tool_calls:
            self._take_text_tool_calls(choice, tools)
        return choice

    def _take_text_tool_calls(self, choice, tools: List[Dict]) -> None:
        """Make the tool calls the model wrote in its text real tool calls."""
        calls, rest = parse_text_tool_calls(choice.message.content or "", tools)
        if not calls:
            return
        data = choice.message.model_dump()
        data["content"] = rest or None
        data["tool_calls"] = [{"id": f"call_text_{self.usage['llm_calls']}_{i}", "type": "function",
                               "function": {"name": c["name"],
                                            "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                              for i, c in enumerate(calls)]
        choice.message = type(choice.message).model_validate(data)
        self.usage["text_tool_calls"] += len(calls)
        self._log(getattr(self, "package", None) or "global",
                  f"[text tool calls] {len(calls)} tool call(s) taken from the reply's text: "
                  + ", ".join(c["name"] for c in calls))

    def _create_with_retries(self, **kwargs):
        for attempt in range(len(MODEL_RETRY_WAITS) + 1):
            try:
                return self.client.chat.completions.create(**kwargs)
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                error = e
            except openai.APIStatusError as e:
                if e.status_code not in RETRYABLE_STATUS:
                    raise
                error = e
            if attempt == len(MODEL_RETRY_WAITS):
                raise error
            wait = MODEL_RETRY_WAITS[attempt]
            self._log(getattr(self, "package", None) or "global",
                      f"Model call failed ({getattr(error, 'status_code', type(error).__name__)}): "
                      f"{str(error)[:200]}; retrying in {wait}s")
            time.sleep(wait)

    def _write_status(self, messages: List[Dict]) -> None:
        """Live progress of the current package (scripts/watch_run.py reads it)."""
        if not getattr(self, "package", None):
            return
        status = {"package": self.package, "attempt": self.attempt, "max_attempts": self.max_build_attempts,
                  "round": getattr(self, "round", 0), "max_rounds": self.max_tool_rounds,
                  "context_chars": sum(len(str(m.get("content") or "")) for m in messages),
                  "builds": list(getattr(self, "builds", [])), "usage": self.usage,
                  "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            with open(os.path.join(self.log_dir, f"{self.package}_status.json"), "w") as f:
                json.dump(status, f, indent=1)
        except OSError:
            pass

    async def _run_one_tool(self, package_name: str, tc) -> Tuple[str, str]:
        tool_name = tc.function.name
        try:
            tool_args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            return tool_name, f"Error: invalid JSON arguments for {tool_name}."
        self.usage["tool_calls"] += 1
        self._log(package_name, f"Tool call: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:500]})")

        if tool_name not in LLM_TOOLS:
            return tool_name, (f"Error: unknown tool {tool_name}. "
                               f"Available tools: {', '.join(LLM_TOOLS)}.")

        if tool_name == "check_build_result" and not self.upload_status.get(package_name, False):
            return tool_name, ("ERROR: Cannot call check_build_result before uploading. "
                               "You must call upload_file_to_obs_tool first.")

        args_key = make_args_key(tool_name, tool_args)
        if REPEAT_GUARD_PER_BUILD:
            args_key += f"#build{len(self.builds)}"
        repeat = json.loads((await self.session.call_tool(
            "check_repeat_tool_call",
            {"tool_name": tool_name, "args_key": args_key, "max_repeat": 3, "package_name": package_name},
        )).content[0].text)
        if not repeat.get("allowed", True):
            return tool_name, (f"{repeat.get('message', 'repeated call blocked')}. "
                               f"Do not call {tool_name} again with the same arguments in this attempt.")

        cache = json.loads((await self.session.call_tool(
            "check_tool_cache", {"call_key": args_key, "tool_name": tool_name, "package_name": package_name},
        )).content[0].text)
        if cache.get("hit"):
            tool_ret = cache["result"]
        else:
            started = time.time()
            try:
                res = await asyncio.wait_for(self.session.call_tool(tool_name, tool_args), timeout=TOOL_TIMEOUT)
                tool_ret = res.content[0].text if res.content else ""
                self._log(package_name, f"Tool return text: {tool_ret[:1000]}")
                if tool_name in CACHEABLE_TOOLS and "error" not in tool_ret.lower():
                    await self.session.call_tool(
                        "cache_tool_result", {"call_key": args_key, "result": tool_ret, "package_name": package_name})
            except asyncio.TimeoutError:
                tool_ret = f"Error: Tool {tool_name} timed out"
            except Exception as e:
                tool_ret = f"Error: Tool {tool_name} failed: {e}"
            bucket = {"upload_file_to_obs_tool": "upload_seconds",
                      "check_build_result": "build_check_seconds"}.get(tool_name, "other_tool_seconds")
            self.timing[bucket] += time.time() - started
            self._track_package_state(tool_name, tool_ret)
        await self.session.call_tool("record_tool_call_history", {"call_key": args_key, "package_name": package_name})

        if tool_name == "upload_file_to_obs_tool" and tool_ret.startswith("Upload successful"):
            self.upload_status[package_name] = True
            self._log(package_name, "✓ Upload marked as successful")
        if tool_name == "check_build_result" and getattr(self, "last_failure_note", ""):
            self._log(package_name, "[framework note] the build failed the same way as the previous one")
            tool_ret += self.last_failure_note
            self.last_failure_note = ""
        return tool_name, tool_ret

    def _track_package_state(self, tool_name: str, tool_ret: str, by_framework: bool = False):
        if tool_name in ("modify_file_tool", "replace_in_file_tool") and tool_ret.startswith("Success"):
            self.dirty = True
            self.changes = getattr(self, "changes", 0) + 1
        elif tool_name == "compress_to_archive_tool" and tool_ret.startswith("Success: Compressed"):
            self.dirty = True
            self.changes = getattr(self, "changes", 0) + 1
        elif tool_name == "upload_file_to_obs_tool" and tool_ret.startswith("Upload successful"):
            self.dirty = False
            self.unchecked_upload = True
            self.changes = getattr(self, "changes", 0) + 1
        elif tool_name == "check_build_result" and tool_ret.startswith("Build result:"):
            self.unchecked_upload = False
            self.changes = getattr(self, "changes", 0) + 1
            line = tool_ret.splitlines()[0]
            self.builds.append(f"{line} (framework)" if by_framework else line)
            self.last_failure_note = self._compare_failure(line)
            if hasattr(self, "network"):
                net = container.network_log(os.path.join(self.stage_root, self.package, "run"))
                for key in self.network:
                    self.network[key].update(net[key])

    def _compare_failure(self, result_line: str) -> str:
        """Remember a failed build's failure; the note for the model when it
        is the same as the previous failure (REPEATED_FAILURE_NOTE)."""
        if "Build failed" not in result_line:
            self.last_failure = None
            return ""
        try:
            with open(os.path.join(self.package_path, "log_failed.txt"), encoding="utf-8", errors="replace") as f:
                signature = failure_signature(f.read())
        except (OSError, AttributeError, TypeError):
            return ""
        previous = getattr(self, "last_failure", None)
        self.last_failure = (signature, f"the previous build (attempt {self.attempt})")
        if not (REPEATED_FAILURE_NOTE and signature and previous and previous[0] == signature):
            return ""
        return (f"\n\n[framework note] This build failed in the same way as {previous[1]}: the same errors "
                "(or the same failing checks and tests), so the changes made since then did not affect this "
                "failure. Reconsider its cause, or take a different approach, before building again.")

    def _save_transcript(self, package_name: str, attempt: int, messages: List[Dict]):
        path = os.path.join(self.log_dir, f"{package_name}_attempt{attempt}_messages.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=1, default=str)
        except Exception as e:
            self._log(package_name, f"Could not save transcript: {e}")

    async def _call(self, tool_name: str, args: Dict, bucket: str) -> str:
        started = time.time()
        try:
            res = await asyncio.wait_for(self.session.call_tool(tool_name, args), timeout=TOOL_TIMEOUT)
            return res.content[0].text if res.content else ""
        finally:
            self.timing[bucket] += time.time() - started

    async def _final_verification(self, package_name: str, package_path: str, summary: Dict) -> bool:
        """Build what the agent left unverified, so that a repair is never lost.

        Runs when the attempt ends with edits that were never uploaded or with an
        upload whose build was never checked.
        """
        steps = []
        try:
            if os.path.isdir(os.path.join(package_path, "extracted")):
                ret = await self._call("compress_to_archive_tool", {"package_path": package_path},
                                       "other_tool_seconds")
                steps.append(f"compress: {ret[:200]}")
                self._track_package_state("compress_to_archive_tool", ret, by_framework=True)
            if self.dirty:
                ret = await self._call("upload_file_to_obs_tool", {"package_path": package_path},
                                       "upload_seconds")
                steps.append(f"upload: {ret[:200]}")
                self._track_package_state("upload_file_to_obs_tool", ret, by_framework=True)
            if self.unchecked_upload:
                ret = await self._call("check_build_result",
                                       {"input_dir": package_path, "package_name": package_name},
                                       "build_check_seconds")
                steps.append(f"check: {ret.splitlines()[0] if ret else ret}")
                self._track_package_state("check_build_result", ret, by_framework=True)
                if ret.startswith(INFRA_ERROR):
                    summary["ended_by"] = "infrastructure_error"
                parsed = await self.session.call_tool(
                    "parse_build_result_tool", {"result_content": ret, "package_name": package_name})
                if json.loads(parsed.content[0].text).get("success", False):
                    summary["verified_by"] = "framework"
        except Exception as e:
            steps.append(f"error: {e}")
        for step in steps:
            self._log(package_name, f"[final check] {step}")
        summary["final_check"] = steps or None
        return summary["verified_by"] == "framework"

    async def _llm_tools_loop(
        self,
        package_name: str,
        package_path: str,
        messages: List[Dict],
        tools: List[Dict],
    ) -> Tuple[str, bool, Dict]:
        assert self.session is not None
        self.upload_status[package_name] = False
        self.builds = []
        self.round = 0
        summary = {"rounds": 0, "ended_by": None, "builds": self.builds,
                   "verified_by": None, "final_check": None}
        latest_text = ""

        try:
            choice = self._chat(messages, tools)
        except Exception as e:
            self._log(package_name, f"Model call failed: {e}")
            summary["ended_by"] = "model_error"
            ok = await self._final_verification(package_name, package_path, summary)
            return f"Model call failed: {e}", ok, summary
        latest_text = choice.message.content or ""

        rounds = quiet = 0
        while choice.message.tool_calls:
            rounds += 1
            self.round = rounds
            summary["rounds"] = rounds
            self._log(package_name, f"== Tool round {rounds} ==")

            reply = {
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [t.model_dump() for t in choice.message.tool_calls],
            }
            if message_reasoning(choice.message):
                reply["reasoning"] = message_reasoning(choice.message)
            messages.append(reply)
            succeeded = False
            changes_before = getattr(self, "changes", 0)
            for tc in choice.message.tool_calls:
                tool_name, tool_ret = await self._run_one_tool(package_name, tc)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_ret})
                if tool_name == "check_build_result":
                    parsed = await self.session.call_tool(
                        "parse_build_result_tool", {"result_content": tool_ret, "package_name": package_name})
                    succeeded = succeeded or json.loads(parsed.content[0].text).get("success", False)
            if succeeded:
                summary.update(ended_by="success", verified_by="agent")
                return latest_text, True, summary
            if any(m.get("role") == "tool" and str(m.get("content", "")).startswith(INFRA_ERROR)
                   for m in messages[-len(choice.message.tool_calls):]):
                self._log(package_name, "Build infrastructure error: ending the run of this package")
                summary["ended_by"] = "infrastructure_error"
                return latest_text, False, summary

            if rounds >= self.max_tool_rounds:
                summary["ended_by"] = "round_limit"
                break
            self._save_transcript(package_name, self.attempt, messages)
            quiet = 0 if getattr(self, "changes", 0) != changes_before else quiet + 1
            if BUILD_DROUGHT_ROUNDS and quiet and quiet % BUILD_DROUGHT_ROUNDS == 0 \
                    and messages[-1].get("role") == "tool":
                summary["drought_notes"] = summary.get("drought_notes", 0) + 1
                self._log(package_name, f"[framework note] {quiet} rounds without a change or a build")
                messages[-1]["content"] += (
                    f"\n\n[framework note] {quiet} rounds without a change to the package or a build. Reading "
                    "and experiments only go so far: apply the change your findings point to and build it, to "
                    "test your hypothesis on the real build; you can go on investigating after the result.")
            left = self.max_tool_rounds - rounds
            if left in ROUND_NOTICE_AT and messages[-1].get("role") == "tool":
                messages[-1]["content"] += (
                    f"\n\n[framework note] {left} round(s) of tool calls left in this attempt. "
                    "If you know the fix, apply it now and start a build; edits that you leave "
                    "unbuilt are built by the framework when the attempt ends.")
            try:
                choice = self._chat(messages, tools)
                retries = summary.setdefault("empty_replies", 0)
                while (not choice.message.tool_calls and not (choice.message.content or "").strip()
                       and retries < EMPTY_REPLY_RETRIES):
                    retries += 1
                    summary["empty_replies"] = retries
                    self._log(package_name, f"Empty model reply; asking to continue ({retries}/{EMPTY_REPLY_RETRIES})")
                    messages.append({"role": "user", "content": (
                        "[framework note] Your last reply was empty. Continue the repair with tool calls; "
                        "reply without tool calls only when you are done.")})
                    choice = self._chat(messages, tools)
                latest_text = choice.message.content or latest_text
            except Exception as e:
                self._log(package_name, f"Model continuation failed: {e}")
                summary["ended_by"] = "model_error"
                break
        else:
            summary["ended_by"] = "no_tool_calls"

        ok = await self._final_verification(package_name, package_path, summary)
        return latest_text, ok, summary

    async def cleanup(self):
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            self._log("global", f"Cleanup error: {e}")
        self.is_session_active = False
        self.session = None
        self._log("global", "Cleanup completed.")


async def main():
    # Choose provider + model here.
    provider = info["LLM_PROVIDER"].lower()
    default_model = os.getenv("LLM_MODEL") or {
        "openai": "gpt-5",
        "qwen": "qwen3-max",
        "claude": "claude-sonnet-4-5-20250929",
        "deepseek": "deepseek-v3",
    }.get(provider)

    llm_cfg = LLMConfig(provider=provider, model=default_model)
    # attempts per package (3 in the paper; BENCH_MAX_ATTEMPTS overrides the
    # config for a single run) and rounds of tool calls per attempt (20)
    attempts = int(os.getenv("BENCH_MAX_ATTEMPTS") or LLM_CFG.get("max_build_attempts", 3))
    cli = AutoRepairClient(llm=llm_cfg, max_build_attempts=attempts,
                           max_tool_rounds=int(LLM_CFG.get("max_tool_rounds", 20)))
    try:
        await cli.process_all_packages()
    finally:
        await cli.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
