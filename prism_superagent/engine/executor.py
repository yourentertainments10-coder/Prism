"""Execute a planned graph through an explicit operation registry."""

from prism_superagent.engine.development import DevelopmentTools
from prism_superagent.engine.dispatcher import calculate_table_stat, execute_operation


class TaskExecutor:
    def __init__(self, workspace):
        self.development = DevelopmentTools(workspace)

    def execute(self, graph):
        state = {}
        for node in graph.nodes:
            if any(dep not in state for dep in node.depends_on):
                raise ValueError(f"Task dependency missing before '{node.node_id}'.")
            inputs = dict(node.inputs)
            if node.depends_on and "table" not in inputs:
                parent = state[node.depends_on[-1]]
                if isinstance(parent, dict) and "records" in parent:
                    inputs["table"] = parent
            if node.operation == "calculate_stat":
                output = calculate_table_stat(inputs["table"], inputs["column"], inputs["operation"])
            elif node.operation in {"git_status", "git_diff", "project_inspect", "python_ast",
                                    "python_compile", "python_lint", "compiler_check", "run_tests",
                                    "patch_test_verify"}:
                output = self.development.execute(node.operation, inputs)
            else:
                output = execute_operation(node.operation, inputs)
            state[node.node_id] = output
            if node.operation in ("calculate_mean", "calculate_sum", "evaluate_expression",
                                  "calculate_stat", "aggregate_monthly"):
                state["result"] = output
            elif len(graph.nodes) == 1:
                state["result"] = output
        return state

