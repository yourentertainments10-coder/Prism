"""Small request-scoped execution traces shared by Prism's runtime layers."""

from contextvars import ContextVar


_active_trace = ContextVar("prism_execution_trace", default=None)


class ExecutionTrace:
    def __init__(self, request, agent_mode=False):
        self.request = str(request or "")[:500]
        self.agent_mode = bool(agent_mode)
        self.route = "unclassified"
        self.capability = "unknown"
        self.model = None
        self.cloud_calls = 0
        self.cloud_calls_complete = True
        self.local_inference_calls = 0
        self.external_api_calls = 0
        self.external_api_calls_complete = True
        self.network_activity = "unknown"
        self.verification = "not_independently_verified"
        self.result_status = "unverified"
        self.tools = []
        self.coding_changes = 0
        self.changed_paths = []
        self.diff_review = "not_run"
        self.repair_attempts = 0

    def set_route(self, route, capability, model=None):
        self.route = route or "unclassified"
        self.capability = capability or "unknown"
        if model:
            self.model = model

    def record(self, event, fields):
        if event == "request_route":
            self.route = fields.get("provider", self.route)
            self.model = fields.get("model", self.model)
        elif event == "round_start":
            provider = str(fields.get("provider", "")).casefold()
            if "anthropic" in provider or "openai_compatible" in provider:
                self.cloud_calls += 1
                self.network_activity = "observed"
                if self.route in ("api_registry", "local_model", "deterministic"):
                    self.route = "cloud_fallback"
                self.model = fields.get("model", self.model)
        elif event == "cloud_provider_call":
            self.cloud_calls += 1
            self.network_activity = "observed"
        elif event == "external_api_request":
            self.external_api_calls += 1
            self.network_activity = "observed"
        elif event == "local_inference_start":
            self.local_inference_calls += 1
            self.capability = fields.get("capability", self.capability)
            self.model = fields.get("model", self.model)
        elif event == "local_summary_end":
            self.capability = "semantic_document_summary"
            self.model = fields.get("model", self.model)
            self.verification = fields.get(
                "verification_status", "structure_valid"
            )
            self.result_status = fields.get("status", "model_generated")
        elif event == "deterministic_task_end":
            self.capability = fields.get("kind", self.capability)
            self.verification = "deterministic_verified"
            self.result_status = fields.get(
                "result_status", "deterministic_verified"
            )
        elif event == "api_registry_success":
            self.capability = fields.get("capability", self.capability)
            self.verification = "api_validated"
            self.result_status = fields.get("result_status", "api_validated")
        elif event == "tool_call_start":
            name = fields.get("name")
            if name and name not in self.tools:
                self.tools.append(name)
            if name in ("run_command", "run_python"):
                self.external_api_calls_complete = False
                self.cloud_calls_complete = False
                self.network_activity = "unknown"
        elif event == "coding_workspace_mutation":
            self.coding_changes += 1
            path = fields.get("path")
            if path and path not in self.changed_paths:
                self.changed_paths.append(str(path)[:300])
        elif event == "coding_verification":
            self.verification = fields.get("verification", self.verification)
            self.result_status = fields.get("result_status", self.result_status)
        elif event == "coding_diff_review":
            self.diff_review = fields.get("status", "completed")
        elif event == "coding_review_requested":
            self.diff_review = "review_requested"
        elif event == "coding_repair_requested":
            self.repair_attempts = max(
                self.repair_attempts, int(fields.get("attempt", 0))
            )

    def snapshot(self):
        return {
            "request": self.request,
            "agent_mode": self.agent_mode,
            "route": self.route,
            "capability": self.capability,
            "model": self.model,
            "cloud_calls": self.cloud_calls,
            "cloud_calls_complete": self.cloud_calls_complete,
            "local_inference_calls": self.local_inference_calls,
            "external_api_calls": self.external_api_calls,
            "tracked_external_calls": self.external_api_calls,
            "external_api_calls_complete": self.external_api_calls_complete,
            "network_activity": self.network_activity,
            "verification": self.verification,
            "result_status": self.result_status,
            "tools": list(self.tools),
            "coding_changes": self.coding_changes,
            "changed_paths": list(self.changed_paths[:50]),
            "diff_review": self.diff_review,
            "repair_attempts": self.repair_attempts,
        }


def bind_trace(trace):
    return _active_trace.set(trace)


def reset_trace(token):
    _active_trace.reset(token)


def record_trace(event, **fields):
    trace = _active_trace.get()
    if trace is not None:
        trace.record(event, fields)


def current_trace():
    return _active_trace.get()
