"""
NVIDIA / OpenAI-compatible provider: client init and the OpenAI-compatible
streaming turn. Extracted from app.py — behavior is unchanged.

Implements the provider interface expected by agent/loop.py: stream_turn()
streams one round of model output (including this provider's rate-limit
model-fallback and tool-rejection retry logic) and returns a normalized turn
result; translate_error() maps a raised exception to a human-readable
message. Tool execution and the multi-round loop live in agent/loop.py, not
here.
"""

import json
import os
import time

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from agent.timing import elapsed_ms, record

load_dotenv()

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
API_KEY = os.getenv("NVIDIA_API_KEY") or ""

client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=API_KEY or "missing",
                timeout=httpx.Timeout(connect=15, read=180, write=30, pool=15),
                max_retries=0)

def stream_turn(model, system_text, convo, tools, sse):
    """Stream one NVIDIA/OpenAI-compatible round, retrying across fallback
    models on rate limits and dropping tools if the model rejects them.
    Yields `reasoning`/`content`/`notice` SSE frames as they stream in, then
    returns a normalized {"content", "tool_calls", "model", "tools"} result
    for agent/loop.py. `model`/`tools` in the result reflect any
    fallback/rejection that happened this round, so the loop continues the
    next round from the same effective values instead of the original ones.
    Each tool call's `arguments_json` is the exact accumulated JSON string
    the model streamed (not re-serialized), matching the original wire
    format byte-for-byte."""
    provider_started = time.perf_counter()
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
                        record("nvidia_retry", model=cand, attempt=attempt + 1,
                               reason="rate_limit",
                               next_action=("retry_same_model" if attempt == 0 and i == 0
                                            else "try_fallback_model"))
                        if attempt == 0 and i == 0:
                            time.sleep(4)   # one quick retry on the chosen model
                            continue
                        break               # move to the next candidate
                    if tools and ("tool" in txt.lower() or "400" in txt):
                        record("nvidia_retry", model=cand, attempt=attempt + 1,
                               reason="tool_rejected", next_action="retry_without_tools")
                        tools = None        # model rejects tools — plain chat
                        continue
                    raise
        raise last

    stream_open_started = time.perf_counter()
    record("nvidia_stream_open_start", model=model)
    try:
        stream, switched = start_stream()
    except Exception as e:
        record("nvidia_stream_open_end", model=model, status="error",
               duration_ms=elapsed_ms(stream_open_started),
               error_type=type(e).__name__)
        record("nvidia_stream_open_error", model=model, error_type=type(e).__name__)
        raise
    record("nvidia_stream_open_end", model=model,
           status="ok", duration_ms=elapsed_ms(stream_open_started))
    if switched:
        yield sse({"notice": f"Model was rate-limited — switched to {model.split('/')[-1]}."})

    content, calls = "", {}
    first_chunk = True
    for chunk in stream:
        if first_chunk:
            first_chunk = False
            record("first_nvidia_chunk", model=model,
                   provider_elapsed_ms=elapsed_ms(provider_started))
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

    tool_calls = []
    for i, c in sorted(calls.items()):
        try:
            args = json.loads(c["args"] or "{}")
        except Exception:
            args = {}
        tool_calls.append({"id": c["id"] or f"call_{i}", "name": c["name"],
                           "args": args, "arguments_json": c["args"] or "{}"})

    return {"content": content, "tool_calls": tool_calls, "model": model, "tools": tools}

def translate_error(e):
    """Map a raised exception to NVIDIA's human-readable error message."""
    msg = str(e)
    if "401" in msg or "Authentication" in msg:
        return ("Authentication failed. Open the .env file and set "
               "NVIDIA_API_KEY=nvapi-... with your key from build.nvidia.com.")
    elif "429" in msg:
        return ("The NVIDIA API is rate-limiting right now (free tier). "
               "Wait ~30 seconds and try again, or switch to another model.")
    return msg
