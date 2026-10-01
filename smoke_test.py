"""Teste de fumaça: sobe o server.py via MCP e chama as ferramentas locais (sem LLM, sem OBS)."""
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=["server.py"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = [t.name for t in (await s.list_tools()).tools]
        print(f"{len(tools)} ferramentas:", ", ".join(tools))
        call = lambda n, a: s.call_tool(n, a)
        pk = json.loads((await call("get_packages_to_process", {"base_dir": "data/case_study/x86_succeed_pro", "result_dir": "result_text_res"})).content[0].text)
        print("pacotes:", pk["packages"])
        init = json.loads((await call("init_package_environment_tool", {"base_dir": "data/case_study/x86_succeed_pro", "package_name": "texmath", "temp_work_dir": "temp_workspace", "result_dir": "result_text_res"})).content[0].text)
        print("init:", init["message"])
        ex = (await call("extract_archive_tool", {"package_path": "temp_workspace/texmath"})).content[0].text
        print("extract:", ex)
        st = (await call("get_structure_of_files", {"package_path": "temp_workspace/texmath"})).content[0].text
        print("estrutura:", len(st), "caracteres; começo:", st[:150].replace("\n", " "))
        log = (await call("get_file_content_tool", {"file_path": "temp_workspace/texmath/log_failed.txt"})).content[0].text
        print("log: linhas =", log.count("\n"), "| erro:", [l for l in log.splitlines() if "unrecognised" in l][0].strip())
        cp = (await call("compress_to_archive_tool", {"package_path": "temp_workspace/texmath"})).content[0].text
        print("compress:", cp)

asyncio.run(main())
