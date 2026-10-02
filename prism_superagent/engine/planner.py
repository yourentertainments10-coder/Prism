"""Turn recognized task intents into explicit, ordered task graphs."""

import uuid

from prism_superagent.engine.task_graph import TaskGraph, TaskNode


class TaskPlanner:
    OPERATIONS = {
        "arithmetic_mean": ("calculate_mean",),
        "arithmetic_sum": ("calculate_sum",),
        "arithmetic_expression": ("evaluate_expression",),
        "statistics": ("statistics",),
        "percentage": ("percentage",),
        "percent_change": ("percent_change",),
        "factorial": ("factorial",),
        "square_root": ("square_root",),
        "gcd": ("gcd",),
        "lcm": ("lcm",),
        "unit_conversion": ("unit_conversion",),
        "temperature_conversion": ("temperature_conversion",),
        "date_difference": ("date_difference",),
        "date_add": ("date_add",),
        "date_add_months": ("date_add_months",),
        "table_stat": ("parse_table", "calculate_stat"),
        "monthly_sales": ("parse_table", "aggregate_monthly"),
        "table_sort": ("table_sort",),
        "table_filter": ("table_filter",),
        "table_deduplicate": ("table_deduplicate",),
        "table_row_count": ("table_row_count",),
        "document_word_count": ("document_word_count",),
        "document_extract": ("document_extract",),
        "document_compare": ("document_compare",),
        "table_extract": ("table_extract",),
        "csv_to_json": ("csv_to_json",),
        "json_format": ("json_format",),
        "json_query": ("json_query",),
        "xml_format": ("xml_format",),
        "xml_query": ("xml_query",),
        "ocr_images": ("ocr_images",),
        "sql_query": ("sql_query",),
        "web_api_get": ("web_api_get",),
        "web_search": ("web_search",),
        "source_verify": ("source_verify",),
        "git_status": ("git_status",),
        "git_diff": ("git_diff",),
        "project_inspect": ("project_inspect",),
        "python_ast": ("python_ast",),
        "python_compile": ("python_compile",),
        "compiler_check": ("compiler_check",),
        "python_lint": ("python_lint",),
        "run_tests": ("run_tests",),
        "patch_test_verify": ("patch_test_verify",),
    }

    def build_graph(self, task):
        operations = self.OPERATIONS.get(task.kind)
        if not operations:
            raise ValueError(f"No deterministic plan exists for task '{task.kind}'.")
        nodes = []
        for i, operation in enumerate(operations):
            if operation == "parse_table":
                inputs = {"table": task.inputs["table"]}
            elif operation == "aggregate_monthly":
                inputs = {"date_column": task.inputs["date_column"],
                          "value_column": task.inputs["value_column"]}
            elif operation == "calculate_stat":
                inputs = {"column": task.inputs["column"],
                          "operation": task.inputs["operation"]}
            else:
                inputs = dict(task.inputs)
            nodes.append(TaskNode(f"step_{i + 1}", operation, inputs,
                                  (f"step_{i}",) if i else ()))
        return TaskGraph(uuid.uuid4().hex[:12], task.kind, task.goal, tuple(nodes))

