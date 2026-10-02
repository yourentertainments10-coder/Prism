"""Classifier -> planner -> router -> executor -> verifier pipeline."""

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from prism_superagent.engine.cache import ResultCache
from prism_superagent.engine.classifier import RequestClassifier
from prism_superagent.engine.executor import TaskExecutor
from prism_superagent.engine.planner import TaskPlanner
from prism_superagent.engine.router import DeterministicRouter
from prism_superagent.engine.verifier import ResultVerifier


@dataclass(frozen=True)
class DeterministicResult:
    task_id: str
    kind: str
    answer: str
    cache_hit: bool
    result_status: str = "deterministic_verified"


class DeterministicEngine:
    NON_CACHEABLE: ClassVar[set[str]] = {
        "ocr_images",
        "git_status",
        "git_diff",
        "project_inspect",
        "python_ast",
        "python_compile",
        "python_lint",
        "compiler_check",
        "run_tests",
        "patch_test_verify",
    }

    def __init__(self, workspace=None):
        self.classifier = RequestClassifier()
        self.planner = TaskPlanner()
        self.router = DeterministicRouter()
        self.executor = TaskExecutor(workspace or "workspace")
        self.verifier = ResultVerifier()
        self.cache = ResultCache()

    def classify(self, user_content, web_mode=False):
        task = self.classifier.classify(user_content, web_mode=web_mode)
        graph = self.planner.build_graph(task) if task is not None else None
        return graph if self.router.route(graph) == "deterministic" else None

    def execute(self, graph):
        key = self.cache.key(graph)
        cacheable = graph.kind not in self.NON_CACHEABLE
        cached = self.cache.get(key) if cacheable else None
        state = (
            {"result": cached} if cached is not None else self.executor.execute(graph)
        )
        if not self.verifier.verify(graph, state):
            raise ValueError(
                "Prism could not independently verify the deterministic result."
            )
        if cached is None and cacheable:
            ttl = (
                120
                if graph.kind == "web_search"
                else 300
                if graph.kind in ("web_api_get", "source_verify")
                else None
            )
            self.cache.put(key, state.get("result"), ttl=ttl)
        return DeterministicResult(
            graph.task_id, graph.kind, self._format(graph, state), cached is not None
        )

    @staticmethod
    def _format(graph, state):
        result = state.get("result", {})
        if graph.kind == "monthly_sales":
            lines = [
                f"Monthly totals for {result['value_column']} ({result['date_column']}):"
            ]
            lines.extend(
                f"- {month}: {_format_number(value)}"
                for month, value in result["monthly_totals"].items()
            )
            lines.append(f"Overall total: {_format_number(result['overall_total'])}")
            lines.append(
                f"Verified {result['rows_included']} of {result['source_rows']} data rows."
            )
            return "\n".join(lines)
        if graph.kind == "table_stat":
            operation = graph.nodes[-1].inputs["operation"]
            labels = {
                "mean": "Average",
                "average": "Average",
                "median": "Median",
                "mode": "Mode",
                "variance": "Variance",
                "standard deviation": "Standard deviation",
                "stdev": "Standard deviation",
                "minimum": "Minimum",
                "min": "Minimum",
                "maximum": "Maximum",
                "max": "Maximum",
                "range": "Range",
                "sum": "Sum",
                "total": "Sum",
                "count": "Count",
            }
            return f"{labels.get(operation, operation.title())} of {graph.nodes[-1].inputs['column']} ({result['count']} values): {_format_number(result['value'])}"
        if graph.kind == "statistics":
            value = result["value"]
            if isinstance(value, dict):
                return "Statistics:\n" + "\n".join(
                    f"- {key}: {_format_number(item)}" for key, item in value.items()
                )
            return f"{result['operation'].title()} of {result['count']} values: {_format_number(value)}"
        if graph.kind == "percentage":
            return (
                f"{_format_number(result['percent'])}% of {_format_number(result['base'])} "
                f"is {_format_number(result['value'])}."
            )
        if graph.kind == "percent_change":
            return f"Percent change: {_format_number(result['value'])}%"
        if graph.kind == "factorial":
            return f"{graph.nodes[0].inputs['value']}! = {result['value']}"
        if graph.kind == "square_root":
            return f"Square root: {_format_number(result['value'])}"
        if graph.kind in ("gcd", "lcm"):
            return f"{graph.kind.upper()}: {_format_number(result['value'])}"
        if graph.kind in ("unit_conversion", "temperature_conversion"):
            return (
                f"{_format_number(graph.nodes[0].inputs['value'])} "
                f"{graph.nodes[0].inputs['source']} = {_format_number(result['value'])} "
                f"{graph.nodes[0].inputs['target']}"
            )
        if graph.kind == "date_difference":
            return f"There are {result['days']} days between {result['start']} and {result['end']}."
        if graph.kind in ("date_add", "date_add_months"):
            return f"Resulting date: {result['date']}"
        if graph.kind in ("table_sort", "table_filter", "table_deduplicate"):
            return _format_table(
                result["headers"],
                result["rows"],
                result.get("row_count"),
                result.get("removed"),
            )
        if graph.kind == "table_row_count":
            return f"Rows: {result['count']}"
        if graph.kind == "document_extract":
            return result["text"][:12_000] or "No extractable text was found."
        if graph.kind == "document_compare":
            return f"Changed lines: {result['changed_lines']}\n```diff\n{result['diff'] or '(no differences)'}\n```"
        if graph.kind in ("json_format", "xml_format"):
            return result["formatted"][:12_000]
        if graph.kind == "json_query":
            return f"{result['path']}:\n```json\n{_json_dump(result['value'])}\n```"
        if graph.kind == "xml_query":
            return f"Found {result['count']} <{result['tag']}> value(s):\n" + "\n".join(
                f"- {item}" for item in result["matches"][:100]
            )
        if graph.kind == "table_extract":
            chunks = []
            for table in result["tables"]:
                chunks.append(
                    f"{table['file']} — {table['sheet']} ({len(table['rows'])} rows)\n"
                    + _format_table(table["headers"], table["rows"])
                )
            return "\n\n".join(chunks)[:12_000]
        if graph.kind == "csv_to_json":
            return "```json\n" + _json_dump(result["json"])[:12_000] + "\n```"
        if graph.kind == "ocr_images":
            return "\n\n".join(
                f"Image {i + 1}:\n{item['text']}"
                for i, item in enumerate(result["texts"])
            )
        if graph.kind == "sql_query":
            return _format_table(
                result["columns"], result["rows"], truncated=result.get("truncated")
            )
        if graph.kind == "web_api_get":
            body = result["body"]
            if not isinstance(body, str):
                body = _json_dump(body)
            return (
                f"Source verified: HTTP {result['status']} over HTTPS\n"
                f"URL: {result['url']}\nRetrieved: {result['retrieved_at']}\n"
                f"SHA-256: {result['sha256']}\n\n{body}"
            )[:14_000]
        if graph.kind == "source_verify":
            return (
                "Source checks (HTTP status and response fingerprint):\n"
                + "\n".join(
                    f"- HTTP {item['status']} — {item['url']}\n  SHA-256: {item['sha256']}"
                    for item in result["sources"]
                )
            )
        if graph.kind == "web_search":
            if not result["results"]:
                return f"No search results found for: {result['query']}"
            return (
                "Search results (retrieved "
                + result["retrieved_at"]
                + "):\n"
                + "\n".join(
                    f"- [{item['title']}]({item['url']}) — {item['snippet']}"
                    for item in result["results"]
                )
            )
        if graph.kind in ("git_status", "git_diff"):
            return result.get("text", "") or "No changes."
        if graph.kind == "project_inspect":
            return (
                f"Files inspected: {result['file_count']}\nBy extension: {_json_dump(result['by_extension'])}\n"
                "\n".join(f"- {name}" for name in result["files"])
            )
        if graph.kind == "python_ast":
            return (
                "Python modules:\n"
                + "\n".join(
                    f"- {module['file']}: {len(module['functions'])} functions, {len(module['classes'])} classes"
                    for module in result.get("modules", [])
                )
                + _format_diagnostics(result)
            )
        if graph.kind in ("python_compile", "python_lint"):
            return (
                f"Files checked: {result['files_checked']}\n"
                + _format_diagnostics(result)
                + ("\nNo issues found." if result["ok"] else "")
            )
        if graph.kind == "compiler_check":
            return result.get("text", "Compiler check complete.")
        if graph.kind == "run_tests":
            return result.get("text", "No test output.")
        if graph.kind == "patch_test_verify":
            return (
                result.get("text", "Patch workflow complete.")
                + "\n"
                + result.get("tests", {}).get("text", "")
                + _format_diagnostics(result.get("compile", {}))
            )
        if graph.kind == "arithmetic_mean":
            return f"Average of {len(graph.nodes[0].inputs['values'])} numbers: {_format_number(result['value'])}"
        if graph.kind == "arithmetic_sum":
            return f"Sum of {len(graph.nodes[0].inputs['values'])} numbers: {_format_number(result['value'])}"
        return f"Result: {_format_number(result['value'])}"


def _format_number(value):
    if isinstance(value, list):
        return ", ".join(_format_number(item) for item in value)
    if isinstance(value, dict):
        return _json_dump(value)
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def _json_dump(value):
    import json
    from decimal import Decimal

    def encode(item):
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError

    return json.dumps(value, ensure_ascii=False, indent=2, default=encode)


def _format_table(headers, rows, row_count=None, removed=None, truncated=None):
    if not headers:
        return "No columns were returned."
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows[:100]:
        values = [
            row.get(header, "") if isinstance(row, dict) else row[i]
            for i, header in enumerate(headers)
        ]
        lines.append(
            "| "
            + " | ".join(
                str(value).replace("|", "\\|").replace("\n", " ") for value in values
            )
            + " |"
        )
    suffix = []
    if row_count is not None:
        suffix.append(f"Rows: {row_count}")
    if removed is not None:
        suffix.append(f"Duplicate rows removed: {removed}")
    if truncated:
        suffix.append("Output limited to the first 500 rows.")
    return "\n".join(lines + (["\n" + " · ".join(suffix)] if suffix else []))


def _format_diagnostics(result):
    lines = []
    for error in result.get("errors", []):
        lines.append(f"- ERROR {error.get('file', '')}: {error.get('error', '')}")
    for warning in result.get("warnings", []):
        lines.append(f"- WARNING {warning}")
    return "\n" + "\n".join(lines) if lines else ""
