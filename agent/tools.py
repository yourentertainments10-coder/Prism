"""
Provider-independent tool system for the agent loop: tool schemas (OpenAI
function-calling shape), their implementations, and the dispatcher that runs
them. Extracted from app.py — behavior is unchanged.
"""

import json
import os
import re
import subprocess
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv
from prism_superagent.tracing import record_trace

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.join(BASE_DIR, "workspace")
IMAGES_DIR = os.path.join(WORKSPACE, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

API_KEY = os.getenv("NVIDIA_API_KEY") or ""

# The "remember" tool needs to write to the app's memory store (Postgres or
# memories.json), which lives in app.py. Importing app.py from here would be
# circular, so app.py injects add_memory via set_memory_writer() at startup.
_memory_writer = None

def set_memory_writer(fn):
    global _memory_writer
    _memory_writer = fn

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
    root = os.path.realpath(WORKSPACE)
    p = os.path.realpath(os.path.join(root, rel))
    try:
        inside_workspace = os.path.commonpath((root, p)) == root
    except ValueError:
        inside_workspace = False
    if not inside_workspace:
        raise ValueError("Path escapes the workspace folder")
    return p

STRIP_TAGS = re.compile(r"<(script|style|nav|header|footer|noscript)[\s\S]*?</\1>|<[^>]+>")

def t_web_search(query):
    record_trace("external_api_request", source="web_search")
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
    record_trace("external_api_request", source="fetch_url")
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
            record_trace("external_api_request", source="image_provider")
            record_trace("cloud_provider_call", provider="nvidia")
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
        record_trace("external_api_request", source="image_provider_fallback")
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
    if _memory_writer:
        _memory_writer(fact.strip(), time.strftime("%Y-%m-%d"))
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
