import json
from pathlib import Path

import agent.loop as agent_loop
import pytest
from prism_superagent.tracing import ExecutionTrace, bind_trace, reset_trace


class ScriptedProvider:
    __name__ = "scripted_provider"

    def __init__(self, read_for_review):
        self.turn = 0
        self.read_for_review = read_for_review

    @staticmethod
    def _call(call_id, name, args):
        return {
            "id": call_id,
            "name": name,
            "args": args,
            "arguments_json": json.dumps(args),
        }

    def stream_turn(self, model, system, convo, tools, sse):
        self.turn += 1
        incorrect = 'def reverse_text(value):\n    return value\n'
        corrected = 'def reverse_text(value):\n    return value[::-1]\n'
        test_file = (
            "from string_utils import reverse_text\n\n"
            "def test_reverse_text():\n"
            "    assert reverse_text('prism') == 'msirp'\n"
        )
        calls = {
            1: [
                self._call(
                    "1",
                    "write_file",
                    {"path": "string_utils.py", "content": incorrect},
                ),
                self._call(
                    "2",
                    "write_file",
                    {"path": "test_string_utils.py", "content": test_file},
                ),
            ],
            3: [
                self._call(
                    "3",
                    "write_file",
                    {"path": "string_utils.py", "content": corrected},
                )
            ],
        }
        if self.read_for_review:
            calls[5] = [self._call("5", "read_file", {"path": "string_utils.py"})]
        content = f"Scripted turn {self.turn}"
        yield sse({"content": content})
        return {"content": content, "tool_calls": calls.get(self.turn, [])}

    @staticmethod
    def translate_error(exc):
        return str(exc)


@pytest.mark.parametrize(
    ("read_for_review", "expected_review"),
    [(True, "reviewed_by_model"), (False, "review_incomplete")],
)
def test_coding_loop_repairs_failed_test_and_reviews_changed_file(
    tmp_path, monkeypatch, read_for_review, expected_review
):
    def run_tool(name, args):
        path = Path(tmp_path, args["path"])
        if name == "write_file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return f"Wrote {args['path']}"
        if name == "read_file":
            return path.read_text(encoding="utf-8")
        raise AssertionError(f"Unexpected tool: {name}")

    monkeypatch.setattr(agent_loop, "WORKSPACE", str(tmp_path))
    monkeypatch.setattr(agent_loop, "run_tool", run_tool)
    trace = ExecutionTrace("Add string reversal and tests", agent_mode=True)
    trace.set_route("mock", "agent_tool_workflow", "mock")
    token = bind_trace(trace)
    try:
        events = list(
            agent_loop.run(
                ScriptedProvider(read_for_review),
                "mock",
                "",
                [],
                [],
                lambda event: json.dumps(event),
            )
        )
    finally:
        reset_trace(token)

    snapshot = trace.snapshot()
    assert snapshot["repair_attempts"] == 1
    assert snapshot["verification"] == "tests_passed"
    assert snapshot["diff_review"] == expected_review
    assert snapshot["coding_changes"] == 3
    assert snapshot["tracked_external_calls"] == 0
    assert snapshot["network_activity"] == "unknown"
    assert "".join(json.loads(event).get("content", "") for event in events if event)
    assert any(json.loads(event).get("done") for event in events if event)
    assert "return value[::-1]" in (tmp_path / "string_utils.py").read_text()
