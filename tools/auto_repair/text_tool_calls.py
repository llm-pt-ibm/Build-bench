"""Tool calls a model wrote as text. Model servers turn a model's tool calls
into the API's tool_calls only when their parser knows the model's format
(vLLM's --tool-call-parser, llama.cpp's --jinja, Ollama's templates); when
it does not, the calls arrive as text in the reply and the attempt would end
with "no tool calls". parse() finds them in the formats of the common open
models:

  Hermes, Qwen 2.5/3:   <tool_call>{"name": ..., "arguments": {...}}</tool_call>
  Qwen3-Coder:          <tool_call><function=NAME><parameter=KEY>VALUE</parameter></function></tool_call>
  GLM 4.5:              <tool_call>NAME<arg_key>KEY</arg_key><arg_value>VALUE</arg_value></tool_call>
  Mistral:              [TOOL_CALLS][{"name": ..., "arguments": {...}}]  or  [TOOL_CALLS]NAME[ARGS]{...}
  Llama 3.x:            <|python_tag|>{"name": ..., "parameters": {...}}
  DeepSeek V3/R1:       <｜tool▁call▁begin｜>function<｜tool▁sep｜>NAME ```json {...}``` <｜tool▁call▁end｜>
  gpt-oss (harmony):    to=functions.NAME ... <|message|>{...}<|call|>
  a reply that is only JSON calls (bare or in ```json fences)

Only calls of the given tools are taken; XML-style values are converted to
the type the tool's schema gives (integers, booleans, objects)."""
import json
import re

_DS_BEGIN, _DS_SEP, _DS_END = "<｜tool▁call▁begin｜>", "<｜tool▁sep｜>", "<｜tool▁call▁end｜>"
_DS_MARKERS = ("<｜tool▁calls▁begin｜>", "<｜tool▁calls▁end｜>")


def _schemas(tools: list) -> dict:
    """{tool name: {parameter: JSON schema type}} from OpenAI-format tools."""
    out = {}
    for t in tools or []:
        fn = t.get("function", t)
        props = (fn.get("parameters") or {}).get("properties") or {}
        out[fn.get("name")] = {k: (v or {}).get("type") for k, v in props.items()}
    return out


def _json_values(text: str) -> list:
    """Every JSON object or array that starts in text (in order)."""
    decoder, values, i = json.JSONDecoder(), [], 0
    while True:
        starts = [p for p in (text.find("{", i), text.find("[", i)) if p >= 0]
        if not starts:
            return values
        i = min(starts)
        try:
            value, end = decoder.raw_decode(text, i)
            values.append((value, i, end))
            i = end
        except ValueError:
            i += 1


def _typed(value: str, kind) -> object:
    value = value.strip("\n")
    if kind in (None, "string"):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _call(obj, schemas: dict):
    """{"name", "arguments"} from a JSON call object, or None."""
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("function"), dict):            # {"type": "function", "function": {...}}
        obj = obj["function"]
    name = obj.get("name")
    args = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except ValueError:
            return None
    if name not in schemas or not isinstance(args, dict):
        return None
    return {"name": name, "arguments": args}


def _calls_in_json(text: str, schemas: dict) -> list:
    calls = []
    for value, _, _ in _json_values(text):
        for obj in value if isinstance(value, list) else [value]:
            call = _call(obj, schemas)
            if call:
                calls.append(call)
    return calls


def _xml_function(body: str, schemas: dict):
    m = re.search(r"<function=([\w.\-]+)>(.*?)(?:</function>|$)", body, re.S)
    if not m or m.group(1) not in schemas:
        return None
    name, types = m.group(1), schemas[m.group(1)]
    args = {k: _typed(v, types.get(k))
            for k, v in re.findall(r"<parameter=([\w\-]+)>(.*?)(?:</parameter>|(?=<parameter=)|$)", m.group(2), re.S)}
    return {"name": name, "arguments": args}


def _glm_call(body: str, schemas: dict):
    name = body.split("<arg_key>", 1)[0].strip()
    if name not in schemas:
        return None
    types = schemas[name]
    args = {k.strip(): _typed(v, types.get(k.strip()))
            for k, v in re.findall(r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>", body, re.S)}
    return {"name": name, "arguments": args}


def parse(text: str, tools: list):
    """The tool calls written in a reply's text: ([{"name", "arguments"}],
    the text without them). ([], text) when there are none."""
    if not text:
        return [], text or ""
    schemas = _schemas(tools)
    calls, spans = [], []

    # <tool_call> blocks (the last one may be unclosed)
    for m in re.finditer(r"<tool_call>(.*?)(?:</tool_call>|$)", text, re.S):
        body = m.group(1).strip()
        found = (_calls_in_json(body, schemas) if body.startswith(("{", "[")) else
                 [c for c in [_xml_function(body, schemas) if "<function=" in body else _glm_call(body, schemas)]
                  if c])
        if found:
            calls += found
            spans.append(m.span())
    # <function=...> without <tool_call>
    if not calls and "<function=" in text:
        for m in re.finditer(r"<function=[\w.\-]+>.*?(?:</function>|$)", text, re.S):
            call = _xml_function(m.group(0), schemas)
            if call:
                calls.append(call)
                spans.append(m.span())
    # Mistral
    if not calls and "[TOOL_CALLS]" in text:
        start = text.index("[TOOL_CALLS]")
        rest = text[start + len("[TOOL_CALLS]"):]
        for m in re.finditer(r"([\w.\-]+)\[ARGS\]", rest):
            try:
                args, _ = json.JSONDecoder().raw_decode(rest, m.end())
            except ValueError:
                continue
            call = _call({"name": m.group(1), "arguments": args}, schemas)
            if call:
                calls.append(call)
        calls = calls or _calls_in_json(rest, schemas)
        if calls:
            spans.append((start, len(text)))
    # DeepSeek
    if not calls and _DS_BEGIN in text:
        for m in re.finditer(re.escape(_DS_BEGIN) + r"(.*?)" + re.escape(_DS_SEP) + r"(.*?)(?:"
                             + re.escape(_DS_END) + r"|$)", text, re.S):
            head, body = m.group(1).strip(), m.group(2)
            if head == "function":                         # V3/R1: name on the first line, then fenced JSON
                name, _, body = body.partition("\n")
            else:                                          # V3.1: the name before the separator
                name = head
            values = _json_values(body)
            call = _call({"name": name.strip(), "arguments": values[0][0] if values else {}}, schemas)
            if call:
                calls.append(call)
                spans.append(m.span())
    # gpt-oss (harmony)
    if not calls and "to=functions." in text:
        for m in re.finditer(r"(?:<\|start\|>\w*)?(?:<\|channel\|>\w+\s*)?to=functions\.([\w.\-]+).*?"
                             r"<\|message\|>(.*?)(?:<\|call\|>|$)", text, re.S):
            values = _json_values(m.group(2))
            call = _call({"name": m.group(1), "arguments": values[0][0] if values else {}}, schemas)
            if call:
                calls.append(call)
                spans.append(m.span())
    # Llama 3.x
    if not calls and "<|python_tag|>" in text:
        start = text.index("<|python_tag|>")
        calls = _calls_in_json(text[start:], schemas)
        if calls:
            spans.append((start, len(text)))
    # a reply that is nothing but calls, bare or in ``` fences
    if not calls:
        bare = re.sub(r"```(?:json)?", "", text).strip()
        values = _json_values(bare)
        if values and values[0][1] == 0 and values[-1][2] == len(bare) and \
                "".join(bare[a:b] for (_, _, a), (_, b, _) in zip(values, values[1:])).strip(" \n,") == "":
            found = _calls_in_json(bare, schemas)
            if found and len(found) == sum(len(v) if isinstance(v, list) else 1 for v, _, _ in values):
                return found, ""

    if not calls:
        return [], text
    rest, last = [], 0
    for a, b in sorted(spans):
        rest.append(text[last:a])
        last = max(last, b)
    rest.append(text[last:])
    remaining = "".join(rest)
    for marker in _DS_MARKERS + ("<|python_tag|>",):
        remaining = remaining.replace(marker, "")
    return calls, remaining.strip()
