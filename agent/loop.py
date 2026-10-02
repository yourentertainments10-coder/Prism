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

import json
import time

from agent.tools import WORKSPACE, run_tool
from agent.timing import elapsed_ms, record
from prism_superagent.engine.development import DevelopmentTools
from prism_superagent.tracing import current_trace

def run(provider, model, system_text, convo, tools, sse):
    """Drive the streaming agent loop for one /api/chat request: up to 12
    rounds of (call the provider for one turn, execute any requested tools,
    continue) until the provider returns no tool calls. `convo` is mutated
    in place (assistant/tool messages appended), exactly as when this loop
    was duplicated inside each provider's own generator; `sse` is the same
    SSE-frame formatter from app.py's /api/chat."""
    trace = current_trace()
    coding_mode = bool(trace and trace.agent_mode)
    development = DevelopmentTools(WORKSPACE) if coding_mode else None
    last_verified_changes = 0
    repair_attempts = 0
    review_needs_file_reads = False
    review_file_read = False
    try:
        for round_number in range(1, 13):
            round_started = time.perf_counter()
            record("round_start", round_number=round_number,
                   provider=provider.__name__, model=model)
            buffered_content = []

            def turn_sse(event):
                if coding_mode and trace.coding_changes and "content" in event:
                    buffered_content.append(sse(event))
                    return ""
                return sse(event)

            try:
                turn = yield from provider.stream_turn(
                    model, system_text, convo, tools, turn_sse
                )
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
                if coding_mode and trace.coding_changes > last_verified_changes:
                    verification = development.verify_workspace_changes(
                        trace.changed_paths
                    )
                    last_verified_changes = trace.coding_changes
                    record(
                        "coding_verification",
                        verification=verification["verification"],
                        result_status=(
                            "coding_checks_passed"
                            if verification["verification"]
                            in ("tests_passed", "compile_only_no_tests")
                            else "verification_not_available"
                            if verification["ok"]
                            else "verification_failed"
                        ),
                    )
                    tests = verification["tests"]
                    syntax = verification["syntax"]
                    if not verification["ok"] and repair_attempts < 2:
                        repair_attempts += 1
                        details = json.dumps(
                            {
                                "syntax": syntax,
                                "formatting": verification["formatting"],
                                "tests": tests,
                            },
                            ensure_ascii=False,
                        )[:12_000]
                        convo.append({
                            "role": "assistant",
                            "content": turn.get("content") or "",
                        })
                        convo.append({
                            "role": "user",
                            "content": (
                                "Prism's automatic post-edit verification failed. "
                                "Inspect this report, repair the code, and run the "
                                "relevant checks again. Do not claim completion until "
                                f"they pass.\n\n{details}"
                            ),
                        })
                        record("coding_repair_requested", attempt=repair_attempts)
                        yield sse({
                            "notice": f"Automatic verification failed; asking the coding agent to repair it (attempt {repair_attempts}/2)."
                        })
                        continue
                    if not verification["ok"]:
                        yield sse({
                            "notice": "Automatic verification still fails after two repair attempts; review the execution trace before using the changes."
                        })
                    else:
                        diff = development.execute("git_diff", {})
                        diff_status = "review_available" if diff.get("ok") else "git_diff_unavailable"
                        review_needs_file_reads = not diff.get("ok")
                        review_file_read = False
                        record("coding_diff_review", status=diff_status)
                        summary = {
                            "changed_paths": trace.changed_paths[:50],
                            "verification": verification["verification"],
                            "syntax": syntax.get("text", "")[:3000],
                            "lint": verification["lint"].get("text", "")[:3000],
                            "formatting": verification["formatting"].get("text", "")[:3000],
                            "tests": tests.get("text", "")[:5000],
                            "diff": diff.get("text", "")[:12_000],
                        }
                        convo.append({
                            "role": "assistant",
                            "content": turn.get("content") or "",
                        })
                        convo.append({
                            "role": "user",
                            "content": (
                                "Automatic post-edit checks completed. Review the "
                                "available diff and check output below. If the diff "
                                "is unavailable, inspect changed_paths with read_file. "
                                "If you find "
                                "a defect, fix it and rerun checks; otherwise give a "
                                "concise final report. State clearly if tests were not "
                                "available or the diff could not be inspected.\n\n"
                                + json.dumps(summary, ensure_ascii=False)
                            ),
                        })
                        record("coding_review_requested")
                        yield sse({
                            "notice": "Post-edit checks completed; reviewing the change summary before the final response."
                        })
                        continue
                elif coding_mode and trace.coding_changes and trace.diff_review == "review_requested":
                    if not review_needs_file_reads or review_file_read:
                        record("coding_diff_review", status="reviewed_by_model")
                    else:
                        record("coding_diff_review", status="review_incomplete")
                        yield sse({
                            "notice": "The Git diff is unavailable and the changed files were not read during the review step; review is incomplete."
                        })
                for event in buffered_content:
                    yield event
                break

            convo.append({"role": "assistant", "content": turn.get("content") or None,
                          "tool_calls": [{"id": tc["id"], "type": "function",
                                          "function": {"name": tc["name"], "arguments": tc["arguments_json"]}}
                                         for tc in tool_calls]})
            for tc in tool_calls:
                args = tc["args"] or {}
                record("tool_call_start", name=tc["name"])
                label = args.get("query") or args.get("url") or args.get("prompt") \
                    or args.get("path") or args.get("command") or args.get("fact") or ""
                yield sse({"tool": tc["name"], "label": str(label)[:120]})
                result = run_tool(tc["name"], args)
                if (coding_mode and trace.diff_review == "review_requested"
                        and tc["name"] == "read_file"
                        and not str(result).startswith("Tool error:")):
                    review_file_read = True
                if tc["name"] == "write_file" and str(result).startswith("Wrote "):
                    record(
                        "coding_workspace_mutation",
                        path=args.get("path"),
                    )
                elif coding_mode and tc["name"] in ("run_command", "run_python"):
                    record("coding_workspace_mutation")
                yield sse({"tool_done": tc["name"]})
                convo.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
        if coding_mode and trace.coding_changes and trace.diff_review != "reviewed_by_model":
            yield sse({
                "notice": "The bounded coding workflow ended before the final review completed; inspect the execution trace and workspace changes."
            })
        yield sse({"done": True})
    except Exception as e:
        record("agent_loop_error", provider=provider.__name__, model=model,
               error_type=type(e).__name__)
        yield sse({"error": provider.translate_error(e)})
