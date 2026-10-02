"""
Anthropic (Claude) provider: client init, OpenAI<->Claude tool/message format
adapters, and the Claude-specific streaming turn. Extracted from app.py —
behavior is unchanged.

Implements the provider interface expected by agent/loop.py: stream_turn()
streams one round of model output and returns a normalized turn result;
translate_error() maps a raised exception to a human-readable message. Tool
execution and the multi-round loop live in agent/loop.py, not here.
"""

import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or ""

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or "missing")

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

def stream_turn(model, system_text, convo, tools, sse):
    """Stream one Claude round. `convo` is read (not mutated here — the
    agent loop owns appending messages); `sse` is the SSE-frame formatter
    from app.py's /api/chat. Yields `content` SSE frames as text streams in,
    then returns a normalized {"content", "tool_calls"} result for
    agent/loop.py. Each tool call's `arguments_json` is the exact string to
    place in the assistant message's function.arguments field."""
    claude_tools = to_claude_tools(tools) if tools else None
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
    return {"content": content,
            "tool_calls": [{"id": b.id, "name": b.name, "args": b.input or {},
                            "arguments_json": json.dumps(b.input)} for b in tool_uses]}

def translate_error(e):
    """Map a raised exception to Claude's human-readable error message."""
    msg = str(e)
    if "401" in msg or "authentication" in msg.lower():
        return ("Authentication failed. Open the .env file and set "
               "ANTHROPIC_API_KEY=sk-ant-... with your key from console.anthropic.com.")
    elif "429" in msg or "overloaded" in msg.lower():
        return "Claude API is rate-limited or overloaded right now. Wait a bit and try again."
    return msg
