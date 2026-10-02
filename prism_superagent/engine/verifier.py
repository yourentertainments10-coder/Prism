"""Independent result checks for deterministic operations."""

from collections import defaultdict
from decimal import Decimal
from statistics import mean, median, multimode, pstdev, stdev, variance

from prism_superagent.engine.dispatcher import _month_key, evaluate_expression
from prism_superagent.engine.math_tools import execute_math
from prism_superagent.engine.tabular import decimal_value


class ResultVerifier:
    def verify(self, graph, state):
        result = state.get("result")
        if graph.kind == "arithmetic_mean":
            values = graph.nodes[0].inputs["values"]
            return bool(values) and result["value"] == sum(values, Decimal(0)) / Decimal(len(values))
        if graph.kind == "arithmetic_sum":
            values = graph.nodes[0].inputs["values"]
            return bool(values) and result["value"] == sum(values, Decimal(0))
        if graph.kind == "arithmetic_expression":
            return result["value"] == evaluate_expression(graph.nodes[0].inputs["expression"])
        if graph.kind == "statistics":
            expected = execute_math(graph.kind, graph.nodes[0].inputs)
            return result.get("count") == expected.get("count") and result.get("value") == expected.get("value")
        if graph.kind in ("unit_conversion", "temperature_conversion", "date_difference",
                          "date_add", "date_add_months", "percentage", "percent_change",
                          "factorial", "square_root", "gcd", "lcm"):
            expected = execute_math(graph.kind, graph.nodes[0].inputs)
            return result == expected
        if graph.kind == "table_stat":
            inputs = dict(graph.nodes[-1].inputs)
            inputs["table"] = graph.nodes[0].inputs["table"]
            table, column = inputs["table"], inputs["column"]
            values = [decimal_value(row.get(column, "")) for row in table["records"]]
            values = [value for value in values if value is not None]
            if not values:
                return False
            operation = inputs["operation"]
            if operation in ("mean", "average"):
                expected = mean(values)
            elif operation == "median":
                expected = median(values)
            elif operation == "mode":
                modes = multimode(values)
                expected = modes[0] if len(modes) == 1 else modes
            elif operation == "variance":
                expected = variance(values) if len(values) > 1 else Decimal(0)
            elif operation in ("standard deviation", "stdev"):
                expected = stdev(values) if len(values) > 1 else Decimal(0)
            elif operation in ("minimum", "min"):
                expected = min(values)
            elif operation in ("maximum", "max"):
                expected = max(values)
            elif operation == "range":
                expected = max(values) - min(values)
            elif operation in ("sum", "total"):
                expected = sum(values, Decimal(0))
            else:
                expected = len(values)
            return result["value"] == expected and result["count"] == len(values)
        if graph.kind == "monthly_sales":
            inputs = dict(graph.nodes[-1].inputs)
            inputs["table"] = graph.nodes[0].inputs["table"]
            totals = defaultdict(Decimal)
            included = 0
            for row in inputs["table"]["records"]:
                month = _month_key(row.get(inputs["date_column"], ""))
                amount = decimal_value(row.get(inputs["value_column"], ""))
                if month and amount is not None:
                    totals[month] += amount
                    included += 1
            expected = dict(sorted(totals.items()))
            return (bool(expected) and result.get("monthly_totals") == expected
                    and result.get("overall_total") == sum(expected.values(), Decimal(0))
                    and result.get("rows_included") == included)
        if graph.kind in ("web_api_get", "web_search", "source_verify"):
            if graph.kind == "web_search":
                return result.get("status") == 200 and isinstance(result.get("results"), list)
            if graph.kind == "source_verify":
                sources = result.get("sources", [])
                return (result.get("verified") is True and len(sources) ==
                        len(graph.nodes[0].inputs["urls"]) and
                        all(item.get("status") == 200 and item.get("verified") is True and
                            bool(item.get("sha256")) for item in sources))
            return result.get("verified") is True
        if graph.kind == "run_tests":
            return "ok" in result and ("text" in result or result.get("tests_found") is False)
        if graph.kind == "patch_test_verify":
            return result.get("ok") is True or result.get("rolled_back") is True
        if graph.kind in ("python_lint", "python_compile", "compiler_check"):
            return isinstance(result.get("errors"), list) and isinstance(result.get("warnings"), list)
        if graph.kind == "sql_query":
            return isinstance(result.get("columns"), list) and isinstance(result.get("rows"), list)
        if graph.kind in ("json_format", "xml_format"):
            return result.get("valid") is True
        if graph.kind == "document_compare":
            return isinstance(result.get("diff"), str) and result.get("changed_lines", -1) >= 0
        if graph.kind == "ocr_images":
            return len(result.get("texts", [])) == len(graph.nodes[0].inputs["images"])
        if graph.kind == "table_row_count":
            return result.get("count") == len(graph.nodes[0].inputs["table"]["records"])
        if graph.kind == "document_word_count":
            return (
                result.get("total_word_count")
                == sum(item.get("word_count", -1) for item in result.get("documents", []))
                and all(isinstance(item.get("word_count"), int) and item["word_count"] >= 0
                        for item in result.get("documents", []))
            )
        if graph.kind in ("table_sort", "table_filter", "table_deduplicate", "table_extract",
                          "csv_to_json", "document_extract", "json_query", "xml_query", "git_status", "git_diff",
                          "project_inspect", "python_ast"):
            return result is not None
        return False

