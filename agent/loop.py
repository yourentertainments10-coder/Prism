"""
Provider-independent agent orchestration: the streaming round-loop shared by
every provider. Extracted from providers/anthropic.py and
providers/openai_compatible.py — behavior is unchanged.

Interface expected from a provider module:

  stream_turn(model, system_text, convo, tools, sse) -> generator
      Yields SSE frames (via `sse(...)`) for exactly one round of streamed
      model output — provider-specific frames (content/reasoning/notice) are
      the provider's own concern — then returns a normalized turn result:
          {
            "content": str,             # accumulated assistant text this round
            "tool_calls": [             # empty/falsy => final answer, stop looping
              {"id": str, "name": str, "args": dict, "arguments_json": str},
              ...
            ],
            "model": str,               # optional: effective model for the next round
            "tools": list | None,       # optional: effective tools for the next round
          }
      "model"/"tools" let a provider carry fallback/rejection state (e.g.
      NVIDIA's rate-limit model switch or tool-rejection) forward into the
      next round; a provider that has no such state (Anthropic) simply omits
      them and the loop keeps using the same values.

  translate_error(exc) -> str
      Turns a raised exception into the provider's human-readable error
      message.
"""

import time

from agent.tools import run_tool
from agent.timing import elapsed_ms, record

def run(provider, model, system_text, convo, tools, sse):
    """Drive the streaming agent loop for one /api/chat request: up to 10
    rounds of (call the provider for one turn, execute any requested tools,
    continue) until the provider returns no tool calls. `convo` is mutated
    in place (assistant/tool messages appended), exactly as when this loop
    was duplicated inside each provider's own generator; `sse` is the same
    SSE-frame formatter from app.py's /api/chat."""
    try:
        for round_number in range(1, 11):
            round_started = time.perf_counter()
            record("round_start", round_number=round_number,
                   provider=provider.__name__, model=model)
            try:
                turn = yield from provider.stream_turn(model, system_text, convo, tools, sse)
            except Exception as e:
                record("round_error", round_number=round_number,
                       provider=provider.__name__, model=model,
                       error_type=type(e).__name__)
                raise
            finally:
                record("round_end", round_number=round_number,
                       provider=provider.__name__, model=model,
                       duration_ms=elapsed_ms(round_started))
            model = turn.get("model", model)
            tools = turn.get("tools", tools)
            tool_calls = turn.get("tool_calls") or []
            if not tool_calls:
                break

            convo.append({"role": "assistant", "content": turn.get("content") or None,
                          "tool_calls": [{"id": tc["id"], "type": "function",
                                          "function": {"name": tc["name"], "arguments": tc["arguments_json"]}}
                                         for tc in tool_calls]})
            for tc in tool_calls:
                args = tc["args"] or {}
                label = args.get("query") or args.get("url") or args.get("prompt") \
                    or args.get("path") or args.get("command") or args.get("fact") or ""
                yield sse({"tool": tc["name"], "label": str(label)[:120]})
                result = run_tool(tc["name"], args)
                yield sse({"tool_done": tc["name"]})
                convo.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
        yield sse({"done": True})
    except Exception as e:
        record("agent_loop_error", provider=provider.__name__, model=model,
               error_type=type(e).__name__)
        yield sse({"error": provider.translate_error(e)})
