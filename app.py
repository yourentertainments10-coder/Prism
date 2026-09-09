"""
Prism AI — agentic chatbot backend (Flask + NVIDIA inference API + Claude API).

Capabilities: streaming chat, native tool-calling agent loop (web search, page
reading, Python execution, workspace file access, shell commands, image
generation, persistent memory), file/PDF analysis, vision input.
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import uuid

import anthropic
import httpx
import psycopg2
from dotenv import load_dotenv
from flask import (Flask, Response, jsonify, render_template, request,
                   send_from_directory, stream_with_context)
from openai import OpenAI

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(BASE_DIR, "workspace")
IMAGES_DIR = os.path.join(WORKSPACE, "images")
MEMORY_FILE = os.path.join(BASE_DIR, "memories.json")
os.makedirs(IMAGES_DIR, exist_ok=True)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
API_KEY = os.getenv("NVIDIA_API_KEY") or ""
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or ""

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=API_KEY or "missing",
                timeout=httpx.Timeout(connect=15, read=180, write=30, pool=15),
                max_retries=0)

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or "missing")

VISION_MODEL = "meta/llama-3.2-90b-vision-instruct"

MODELS = [
    {"id": "moonshotai/kimi-k3", "name": "Kimi K3", "tag": "best overall", "provider": "nvidia"},
    {"id": "deepseek-ai/deepseek-v4-pro-0813", "name": "DeepSeek V4 Pro", "tag": "reasoning", "provider": "nvidia"},
    {"id": "deepseek-ai/deepseek-v4-flash-0731", "name": "DeepSeek V4 Flash", "tag": "fast", "provider": "nvidia"},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "name": "Nemotron 3 Ultra 550B", "tag": "agent", "provider": "nvidia"},
    {"id": "nvidia/nemotron-3.5-lightning-30b-a3b", "name": "Nemotron 3.5 Lightning", "tag": "fast", "provider": "nvidia"},
    {"id": "nvidia/nemotron-3-super-120b-a12b", "name": "Nemotron 3 Super 120B", "tag": "balanced", "provider": "nvidia"},
    {"id": "openai/gpt-oss-20b", "name": "GPT-OSS 20B", "tag": "open source", "provider": "nvidia"},
    {"id": "mistralai/mistral-large-2-instruct", "name": "Mistral Large 2", "tag": "multilingual", "provider": "nvidia"},
    {"id": "mistralai/codestral-22b-instruct-v0.1", "name": "Codestral 22B", "tag": "code", "provider": "nvidia"},
    {"id": VISION_MODEL, "name": "Llama 3.2 90B Vision", "tag": "images", "provider": "nvidia"},
    {"id": "claude-opus-5", "name": "Claude Opus 5", "tag": "deepest reasoning", "provider": "anthropic"},
    {"id": "claude-sonnet-5", "name": "Claude Sonnet 5", "tag": "flagship, balanced", "provider": "anthropic"},
]

# ---------------------------------------------------------------- memory
# If DATABASE_URL is set (e.g. a free Supabase Postgres project), memories are
# stored there so they survive redeploys/restarts on hosts with an ephemeral
# filesystem (like Render's free tier). Otherwise falls back to memories.json.
DATABASE_URL = os.getenv("DATABASE_URL") or ""

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        return
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY, text TEXT NOT NULL, date TEXT NOT NULL)""")
            conn.commit()
    except Exception as e:
        print(f"[memory] DATABASE_URL set but init failed, memory will not persist: {e}")

def load_memories():
    if DATABASE_URL:
        try:
            with get_db() as conn, conn.cursor() as cur:
                cur.execute("SELECT text, date FROM memories ORDER BY id")
                return [{"text": t, "date": d} for t, d in cur.fetchall()]
        except Exception as e:
            print(f"[memory] DB read failed: {e}")
            return []
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def add_memory(fact, date):
    if DATABASE_URL:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO memories (text, date) VALUES (%s, %s)", (fact, date))
            conn.commit()
        return
    mems = load_memories()
    mems.append({"text": fact, "date": date})
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mems, f, ensure_ascii=False, indent=1)

init_db()

# ---------------------------------------------------------------- system prompt
def system_prompt(agent_mode, web_mode):
    mems = load_memories()
    mem_block = ""
    if mems:
        mem_block = "\n\nSaved memories about the user (from past conversations):\n" + \
            "\n".join(f"- {m['text']}" for m in mems[-40:])
    agent_block = """
- You have filesystem tools (list_files, read_file, write_file), run_python and
  run_command. They operate inside the local 'workspace' folder — a persistent
  scratch area. Use them to create projects, run and test code, and build things
  autonomously like a coding agent. Verify your work by running it.""" if agent_mode else """
- run_python is available for calculations and data work (runs in the local
  workspace folder, files persist between runs)."""
    web_block = """
- The user enabled Web mode: proactively use web_search and fetch_url to ground
  answers in current information, and cite sources with links.""" if web_mode else """
- Use web_search/fetch_url whenever a question may need current or factual
  information you are not sure about."""
    return f"""You are Prism, a highly capable AI assistant (Claude + ChatGPT + a coding
agent in one) running locally with real tools. Today's date: {time.strftime('%Y-%m-%d')}.

Tools guidance:{web_block}{agent_block}
- generate_image creates a real image from a text prompt; the tool returns a
  markdown image link — include that exact markdown in your answer to show it.
- When the user shares something worth remembering long-term (name, preferences,
  ongoing projects, goals), call remember with a short fact. Don't announce it.
- Call tools when useful; after gathering what you need, give the final answer.

Answer style:
- Format in Markdown; fenced code blocks with language tags. Mermaid (```mermaid)
  and SVG (```svg) blocks render visually. ```html blocks get a live Preview button.
- Be concise for simple questions, thorough for complex ones. Cite sources when
  you used the web. Be honest about uncertainty.{mem_block}"""

# ---------------------------------------------------------------- tools
def tool_defs(agent_mode):
    tools = [
        {"type": "function", "function": {
            "name": "web_search",
            "description": "Search the web (DuckDuckGo). Returns titles, URLs and snippets.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}}, "required": ["query"]}}},
        {"type": "function", "function": {
            "name": "fetch_url",
            "description": "Fetch a web page and return its readable text content.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"}}, "required": ["url"]}}},
        {"type": "function", "function": {
            "name": "generate_image",
            "description": "Generate a real image from a text prompt. Returns markdown to embed it.",
            "parameters": {"type": "object", "properties": {
                "prompt": {"type": "string", "description": "Detailed English description of the image"}},
                "required": ["prompt"]}}},
        {"type": "function", "function": {
            "name": "remember",
            "description": "Save a short fact about the user to long-term memory.",
            "parameters": {"type": "object", "properties": {
                "fact": {"type": "string"}}, "required": ["fact"]}}},
        {"type": "function", "function": {
            "name": "run_python",
            "description": "Execute Python code in the persistent workspace folder. Returns stdout/stderr. Files you create persist.",
            "parameters": {"type": "object", "properties": {
                "code": {"type": "string"}}, "required": ["code"]}}},
    ]
    if agent_mode:
        tools += [
            {"type": "function", "function": {
                "name": "list_files",
                "description": "List files in the workspace folder (recursive).",
                "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {
                "name": "read_file",
                "description": "Read a text file from the workspace.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {
                "name": "write_file",
                "description": "Write/overwrite a text file in the workspace.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}}},
            {"type": "function", "function": {
                "name": "run_command",
                "description": "Run a shell command in the workspace folder (30s timeout). Use for pip install, running scripts, git, etc.",
                "parameters": {"type": "object", "properties": {
                    "command": {"type": "string"}}, "required": ["command"]}}},
        ]
    return tools

def safe_path(rel):
    p = os.path.realpath(os.path.join(WORKSPACE, rel))
    if not p.startswith(os.path.realpath(WORKSPACE)):
        raise ValueError("Path escapes the workspace folder")
    return p

STRIP_TAGS = re.compile(r"<(script|style|nav|header|footer|noscript)[\s\S]*?</\1>|<[^>]+>")

def t_web_search(query):
    r = httpx.get("https://html.duckduckgo.com/html/", params={"q": query},
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=12, follow_redirects=True)
    items = re.findall(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
    clean = lambda s: re.sub(r"<[^>]+>", "", s).strip()
    results = [{"title": clean(t), "url": u, "snippet": clean(s)} for u, t, s in items[:6]]
    return json.dumps(results, ensure_ascii=False) if results else "No results found."

def t_fetch_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
    text = STRIP_TAGS.sub(" ", r.text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:9000] or "(page had no readable text)"

def t_generate_image(prompt):
    fname = f"{uuid.uuid4().hex[:12]}.png"
    fpath = os.path.join(IMAGES_DIR, fname)
    # 1) NVIDIA genai endpoints
    for url, payload, extract in [
        ("https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell",
         {"prompt": prompt, "steps": 4, "width": 1024, "height": 1024},
         lambda j: (j.get("artifacts") or [{}])[0].get("base64") or j.get("image") or j.get("b64_json")),
        ("https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-xl",
         {"text_prompts": [{"text": prompt}], "steps": 25, "width": 1024, "height": 1024},
         lambda j: (j.get("artifacts") or [{}])[0].get("base64")),
    ]:
        try:
            r = httpx.post(url, headers={"Authorization": f"Bearer {API_KEY}",
                                         "Accept": "application/json"},
                           json=payload, timeout=90)
            if r.status_code == 200:
                b64 = extract(r.json())
                if b64:
                    import base64
                    with open(fpath, "wb") as f:
                        f.write(base64.b64decode(b64))
                    return f"Image created. Embed it with exactly: ![{prompt[:40]}](/files/images/{fname})"
        except Exception:
            pass
    # 2) Fallback: pollinations.ai (free, no key)
    try:
        from urllib.parse import quote
        r = httpx.get(f"https://image.pollinations.ai/prompt/{quote(prompt[:400])}"
                      f"?width=1024&height=1024&nologo=true",
                      timeout=90, follow_redirects=True)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            with open(fpath, "wb") as f:
                f.write(r.content)
            return f"Image created. Embed it with exactly: ![{prompt[:40]}](/files/images/{fname})"
    except Exception as e:
        return f"Image generation failed: {e}"
    return "Image generation failed: no provider available."

def t_remember(fact):
    add_memory(fact.strip(), time.strftime("%Y-%m-%d"))
    return "Saved."

def t_run_python(code):
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=30, cwd=WORKSPACE)
        out = (p.stdout or "") + (("\nSTDERR:\n" + p.stderr) if p.stderr else "")
        return (out.strip() or "(no output)")[:8000]
    except subprocess.TimeoutExpired:
        return "Error: execution timed out after 30 seconds."
    except Exception as e:
        return f"Error: {e}"

def t_run_command(command):
    try:
        p = subprocess.run(command, shell=True, capture_output=True,
                           text=True, timeout=30, cwd=WORKSPACE)
        out = (p.stdout or "") + (("\nSTDERR:\n" + p.stderr) if p.stderr else "")
        return (out.strip() or f"(exit code {p.returncode}, no output)")[:8000]
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds."
    except Exception as e:
        return f"Error: {e}"

def t_list_files():
    out = []
    for root, dirs, files in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), WORKSPACE)
            out.append(rel.replace("\\", "/"))
    return "\n".join(out[:300]) or "(workspace is empty)"

def t_read_file(path):
    p = safe_path(path)
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()[:20000]

def t_write_file(path, content):
    p = safe_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {len(content)} chars to {path}"

TOOL_IMPL = {
    "web_search": t_web_search,
    "fetch_url": t_fetch_url,
    "generate_image": t_generate_image,
    "remember": t_remember,
    "run_python": t_run_python,
    "run_command": t_run_command,
    "list_files": lambda: t_list_files(),
    "read_file": t_read_file,
    "write_file": t_write_file,
}

def run_tool(name, args):
    fn = TOOL_IMPL.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        return fn(**args) if args else fn()
    except Exception as e:
        return f"Tool error: {e}"

# ---------------------------------------------------------------- claude adapter
def to_claude_tools(openai_tools):
    return [{"name": t["function"]["name"], "description": t["function"]["description"],
             "input_schema": t["function"]["parameters"]} for t in openai_tools]

def to_claude_messages(msgs):
    """Convert the OpenAI-shaped convo (minus the system message) into Claude's
    message format: assistant tool_calls become tool_use blocks, and tool-role
    replies become a user message with tool_result blocks (merged when
    consecutive, since Claude expects all results for one turn together)."""
    out = []
    for m in msgs:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": m.get("content") or ""})
        elif role == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    args = {}
                blocks.append({"type": "tool_use", "id": tc["id"],
                               "name": tc["function"]["name"], "input": args})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"],
                     "content": str(m.get("content", ""))}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
               and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out

# ---------------------------------------------------------------- routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/files/<path:relpath>")
def files(relpath):
    return send_from_directory(WORKSPACE, relpath)

@app.route("/api/config")
def config():
    key = os.getenv("NVIDIA_API_KEY") or ""
    return jsonify({"models": MODELS, "hasKey": bool(key),
                    "keyLooksNvidia": key.startswith("nvapi-")})

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    messages = data.get("messages", [])
    model = data.get("model") or MODELS[0]["id"]
    agent_mode = bool(data.get("agent"))
    web_mode = bool(data.get("web"))

    has_image = any(isinstance(m.get("content"), list) for m in messages)
    if has_image:
        model = VISION_MODEL  # Claude models don't take image input here; NVIDIA vision model covers it

    provider = next((m["provider"] for m in MODELS if m["id"] == model), "nvidia")
    system_text = system_prompt(agent_mode, web_mode)
    convo = [{"role": "system", "content": system_text}] + messages
    tools = None if has_image else tool_defs(agent_mode)  # vision model: plain chat

    def sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    def generate_claude():
        claude_tools = to_claude_tools(tools) if tools else None
        try:
            for _round in range(10):
                kwargs = {"model": model, "max_tokens": 8192,
                          "system": system_text, "messages": to_claude_messages(convo[1:])}
                if claude_tools:
                    kwargs["tools"] = claude_tools
                with anthropic_client.messages.stream(**kwargs) as stream:
                    content = ""
                    for text in stream.text_stream:
                        content += text
                        yield sse({"content": text})
                    final = stream.get_final_message()

                tool_uses = [b for b in final.content if b.type == "tool_use"]
                if not tool_uses:
                    break

                convo.append({"role": "assistant", "content": content or None,
                              "tool_calls": [{"id": b.id, "type": "function",
                                              "function": {"name": b.name, "arguments": json.dumps(b.input)}}
                                             for b in tool_uses]})
                for b in tool_uses:
                    args = b.input or {}
                    label = args.get("query") or args.get("url") or args.get("prompt") \
                        or args.get("path") or args.get("command") or args.get("fact") or ""
                    yield sse({"tool": b.name, "label": str(label)[:120]})
                    result = run_tool(b.name, args)
                    yield sse({"tool_done": b.name})
                    convo.append({"role": "tool", "tool_call_id": b.id, "content": str(result)})
            yield sse({"done": True})
        except Exception as e:
            msg = str(e)
            if "401" in msg or "authentication" in msg.lower():
                msg = ("Authentication failed. Open the .env file and set "
                       "ANTHROPIC_API_KEY=sk-ant-... with your key from console.anthropic.com.")
            elif "429" in msg or "overloaded" in msg.lower():
                msg = "Claude API is rate-limited or overloaded right now. Wait a bit and try again."
            yield sse({"error": msg})

    def generate():
        nonlocal tools
        try:
            FALLBACKS = ["deepseek-ai/deepseek-v4-flash-0731",
                         "nvidia/nemotron-3.5-lightning-30b-a3b",
                         "openai/gpt-oss-20b"]

            def start_stream():
                # try the chosen model, then fall back if it is rate-limited
                nonlocal tools, model
                candidates = [model] + [f for f in FALLBACKS if f != model]
                last = None
                for i, cand in enumerate(candidates):
                    for attempt in range(2):
                        try:
                            s = client.chat.completions.create(
                                model=cand, messages=convo, tools=tools,
                                temperature=0.6, top_p=0.95, max_tokens=8192, stream=True)
                            switched = cand != model
                            model = cand
                            return s, switched
                        except Exception as e:
                            last = e
                            txt = str(e)
                            if "429" in txt:
                                if attempt == 0 and i == 0:
                                    time.sleep(4)   # one quick retry on the chosen model
                                    continue
                                break               # move to the next candidate
                            if tools and ("tool" in txt.lower() or "400" in txt):
                                tools = None        # model rejects tools — plain chat
                                continue
                            raise
                raise last

            for _round in range(10):
                stream, switched = start_stream()
                if switched:
                    yield sse({"notice": f"Model was rate-limited — switched to {model.split('/')[-1]}."})

                content, calls = "", {}
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    d = chunk.choices[0].delta
                    r = getattr(d, "reasoning_content", None)
                    if r:
                        yield sse({"reasoning": r})
                    if d.content:
                        content += d.content
                        yield sse({"content": d.content})
                    for tc in (d.tool_calls or []):
                        slot = calls.setdefault(tc.index, {"id": tc.id or "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["name"] += tc.function.name
                            if tc.function.arguments:
                                slot["args"] += tc.function.arguments

                if not calls:
                    break  # final answer done

                # Execute requested tools, then loop for the model's next turn
                assistant_msg = {"role": "assistant", "content": content or None,
                                 "tool_calls": [{
                                     "id": c["id"] or f"call_{i}", "type": "function",
                                     "function": {"name": c["name"], "arguments": c["args"] or "{}"},
                                 } for i, c in sorted(calls.items())]}
                convo.append(assistant_msg)
                for i, c in sorted(calls.items()):
                    try:
                        args = json.loads(c["args"] or "{}")
                    except Exception:
                        args = {}
                    label = args.get("query") or args.get("url") or args.get("prompt") \
                        or args.get("path") or args.get("command") or args.get("fact") or ""
                    yield sse({"tool": c["name"], "label": str(label)[:120]})
                    result = run_tool(c["name"], args)
                    yield sse({"tool_done": c["name"]})
                    convo.append({"role": "tool",
                                  "tool_call_id": c["id"] or f"call_{i}",
                                  "content": str(result)})
            yield sse({"done": True})
        except Exception as e:
            msg = str(e)
            if "401" in msg or "Authentication" in msg:
                msg = ("Authentication failed. Open the .env file and set "
                       "NVIDIA_API_KEY=nvapi-... with your key from build.nvidia.com.")
            elif "429" in msg:
                msg = ("The NVIDIA API is rate-limiting right now (free tier). "
                       "Wait ~30 seconds and try again, or switch to another model.")
            yield sse({"error": msg})

    gen = generate_claude if provider == "anthropic" else generate
    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/run_code", methods=["POST"])
def run_code():
    code = (request.get_json(force=True).get("code") or "").strip()
    if not code:
        return jsonify({"output": "(no code)"})
    return jsonify({"output": t_run_python(code)})

@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file received"}), 400
    name = f.filename or "file"
    ext = os.path.splitext(name)[1].lower()
    raw = f.read()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return jsonify({"error": f"Could not read file: {e}"}), 400
    limit = 60_000
    return jsonify({"name": name, "text": text[:limit], "truncated": len(text) > limit})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
