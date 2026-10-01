"""Teste offline do laço agente-ferramentas: sem API de LLM e sem OBS.

Troca o modelo por um roteiro fixo de respostas e confere:
- rodada com várias ferramentas em paralelo gera uma conversa válida para a API;
- a trava de repetição bloqueia a 4ª chamada idêntica e avisa no resultado;
- check_build_result antes de upload é recusado;
- o parser só aceita "Build succeeded!" (o original aceitava "broken").
uso: BENCH_CONFIG=config/x86_64_to_ppc64le.yaml python tests/test_offline.py
"""
import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("BENCH_CONFIG", "config/x86_64_to_ppc64le.yaml")
os.environ["API_KEY"] = "offline-test"
os.environ["API_BASE_URL"] = "http://127.0.0.1:9/v1"  # nunca é chamado
os.environ["OBS_USER"] = os.environ["OBS_PASSWORD"] = ""

from openai.types.chat.chat_completion import Choice  # noqa: E402
import client  # noqa: E402

PKG = "zita-resampler"
TMP = f"temp_workspace/{PKG}"


def call(i, name, **args):
    return {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


SCRIPT = [
    # 1: duas ferramentas na mesma resposta (o original quebrava aqui)
    [call(1, "get_file_content_tool", file_path=f"{TMP}/log_failed.txt"),
     call(2, "get_file_content_tool", file_path=f"{TMP}/zita-resampler.spec")],
    # 2: verificar antes de enviar -> deve ser recusado
    [call(3, "check_build_result", input_dir=TMP, package_name=PKG)],
    # 3-6: a mesma leitura 4 vezes -> a 4ª é bloqueada
    [call(4, "get_structure_of_files", package_path=TMP)],
    [call(5, "get_structure_of_files", package_path=TMP)],
    [call(6, "get_structure_of_files", package_path=TMP)],
    [call(7, "get_structure_of_files", package_path=TMP)],
    None,  # 7: resposta só com texto -> fim da tentativa
]


def validate_conversation(messages):
    """Regra da API: toda mensagem do assistente com tool_calls é seguida pelas
    respostas de todos os ids, antes de qualquer outra mensagem."""
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
            assert got == ids, f"mensagem {i}: esperava respostas {ids}, veio {got}"
            i = j
        else:
            i += 1


class ScriptedClient(client.AutoRepairClient):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.step = 0
        self.seen = []

    def _chat(self, messages, tools):
        validate_conversation(messages)
        self.seen = messages
        calls = SCRIPT[self.step]
        self.step += 1
        self.usage["llm_calls"] += 1
        msg = {"role": "assistant", "content": None if calls else "done", "tool_calls": calls}
        return Choice.model_validate({"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                                      "message": msg})


async def main():
    llm = client.LLMConfig(provider="openai", model="scripted")
    cli = ScriptedClient(llm=llm)
    assert await cli.connect()
    try:
        tools = await cli.list_tools_openai_format()
        init = json.loads((await cli.session.call_tool("init_package_environment_tool", {
            "base_dir": cli.base_dir, "package_name": PKG,
            "temp_work_dir": cli.temp_work_dir, "result_dir": cli.result_dir})).content[0].text)
        assert init["success"], init
        cli.usage = {k: 0 for k in ("llm_calls", "tool_calls", "prompt_tokens",
                                    "completion_tokens", "cached_tokens", "cost_usd")}
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "go"}]
        text, ok = await cli._llm_tools_loop(PKG, init["package_path"], messages, tools)
        assert not ok and text == "done"
        tool_msgs = {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
        validate_conversation(messages)
        assert "arm_neon.h" in tool_msgs["call_1"], "log não foi lido"
        assert tool_msgs["call_2"].startswith("#"), "spec não foi lido"
        assert tool_msgs["call_3"].startswith("ERROR: Cannot call check_build_result")
        assert "exceeded max repeat count" in tool_msgs["call_7"], tool_msgs["call_7"][:200]
        assert "truncated" not in tool_msgs["call_4"] or len(tool_msgs["call_4"]) < 41000
        print(f"laço: OK ({cli.usage['tool_calls']} chamadas de ferramenta, conversa válida)")

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
        print("parser: OK (só 'Build succeeded!' conta como sucesso)")

        up = (await cli.session.call_tool("upload_file_to_obs_tool", {"package_path": TMP})).content[0].text
        assert "credentials missing" in up, up
        print("upload sem credenciais: OK (erro explícito, nenhuma chamada ao OBS)")
    finally:
        await cli.cleanup()


asyncio.run(main())
print("\nTODOS OS TESTES PASSARAM")
