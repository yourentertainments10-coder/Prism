"""Conservative rules for work Prism can solve without a model."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from prism_superagent.engine.attachments import request_text
from prism_superagent.engine.data_tools import classify_data_request
from prism_superagent.engine.dev_classifier import classify_development_request
from prism_superagent.engine.documents import classify_document_request
from prism_superagent.engine.math_tools import classify_math_request
from prism_superagent.engine.tabular import attached_tables, monthly_sales_columns
from prism_superagent.engine.web_retrieval import classify_web_request

_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?![\w.])")
_EXPR = re.compile(r"^[\d\s.+*/()%\-]+$")
_NUMBER_LITERAL = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[-+]?\.\d+"
_NUMBER_LIST = re.compile(
    rf"^\s*({_NUMBER_LITERAL})(?:(?:\s*,\s*(?:and\s*)?|\s+and\s+)({_NUMBER_LITERAL}))*\s*[.!?]?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClassifiedTask:
    kind: str
    goal: str
    inputs: dict


def _decimal_numbers(text):
    try:
        return [Decimal(match.replace(",", "")) for match in _NUMBER.findall(text)]
    except InvalidOperation:
        return []


class RequestClassifier:
    """Return a graph only for clearly supported deterministic requests."""

    def classify(self, user_content, web_mode=False):
        if isinstance(user_content, list):
            document_task = classify_document_request(user_content)
            if document_task:
                kind, inputs = document_task
                request = " ".join(item.get("text", "") for item in user_content
                                    if isinstance(item, dict) and item.get("type") == "text")
                return self._graph(kind, request or "Image OCR request", inputs)
            text = " ".join(item.get("text", "") for item in user_content
                            if isinstance(item, dict) and item.get("type") == "text").strip()
            if not text:
                return None
        elif isinstance(user_content, str):
            text = user_content.strip()
        else:
            return None
        if not text:
            return None
        if len(text) > 100_000:
            return None
        if "(truncated)" in text.lower():
            return None
        instructions = request_text(text)
        lower = instructions.lower()

        document_task = classify_document_request(text)
        if document_task:
            kind, inputs = document_task
            return self._graph(kind, text, inputs)
        data_task = classify_data_request(text)
        if data_task:
            kind, inputs = data_task
            return self._graph(kind, text, inputs)
        dev_task = classify_development_request(text)
        if dev_task:
            kind, inputs = dev_task
            return self._graph(kind, text, inputs)
        explicit_web_task = classify_web_request(instructions, web_mode=False)
        if explicit_web_task:
            kind, inputs = explicit_web_task
            return self._graph(kind, text, inputs)

        tables = attached_tables(text)
        if tables and re.search(r"\b(sort|filter|deduplicate|unique rows)\b", lower):
            table = tables[0]
            sort = re.search(r"\bsort\b.*?\bby\s+['\"]?([\w -]+?)['\"]?(?:\s+(ascending|descending|asc|desc))?(?:\?|$)",
                             lower)
            if sort:
                column = next((h for h in table["headers"] if h.lower() == sort.group(1).strip()), None)
                if column:
                    descending = (sort.group(2) or "").startswith("desc")
                    return self._graph("table_sort", text, {"table": table, "column": column,
                                                             "descending": descending})
            filtering = re.search(r"\bwhere\s+['\"]?([\w -]+?)['\"]?\s*(?:=|is|equals)\s*['\"]?([^\"'\n?]+)",
                                  lower)
            if filtering:
                column = next((h for h in table["headers"] if h.lower() == filtering.group(1).strip()), None)
                if column:
                    return self._graph("table_filter", text, {"table": table, "column": column,
                                                               "value": filtering.group(2).strip()})
            if "deduplicate" in lower or "unique rows" in lower:
                return self._graph("table_deduplicate", text, {"table": table})

        if tables and any(word in lower for word in (
                "monthly", "per month", "by month", "sales", "revenue", "average",
                "mean", "sum", "total", "count")):
            for table in tables:
                columns = monthly_sales_columns(table)
                if columns and any(word in lower for word in ("monthly", "per month", "by month")):
                    return self._graph("monthly_sales", text, {
                        "table": table, "date_column": columns[0], "value_column": columns[1]
                    })

        if tables and any(word in lower for word in (
                "average", "mean", "median", "mode", "variance", "stdev", "deviation",
                "min", "max", "range", "sum", "total", "count")):
            return self._classify_table_stat(text, lower, tables)
        if tables:
            return None

        percentile = re.search(r"(\d+(?:\.\d+)?)\s*(?:st|nd|rd|th)?\s+percentile\s+of\s+(.+)$",
                               request_text(text), re.IGNORECASE)
        if percentile and _NUMBER_LIST.fullmatch(percentile.group(2)):
            values = _decimal_numbers(percentile.group(2))
            return self._graph("statistics", text, {"values": values, "operation": "percentile",
                                                     "percentile": float(percentile.group(1))})
        number_text = self._number_list(instructions)
        numbers = _decimal_numbers(number_text) if number_text else []
        math_task = classify_math_request(instructions, numbers)
        if math_task:
            kind, inputs = math_task
            return self._graph(kind, text, inputs)
        if numbers and re.search(r"\b(average|mean)\b", lower):
            return self._graph("arithmetic_mean", text, {"values": numbers})
        if numbers and re.search(r"\b(sum|total|add|plus)\b", lower):
            return self._graph("arithmetic_sum", text, {"values": numbers})

        expression = self._expression(instructions)
        if expression is not None:
            return self._graph("arithmetic_expression", text, {"expression": expression})
        web_task = classify_web_request(instructions, web_mode=web_mode)
        if web_task:
            kind, inputs = web_task
            return self._graph(kind, text, inputs)
        return None

    def _classify_table_stat(self, text, lower, tables):
        for table in tables:
            headers = table["headers"]
            operation_match = re.search(r"\b(average|mean|median|mode|variance|standard deviation|stdev|"
                                        r"minimum|min|maximum|max|range|sum|total|count)\b", lower)
            operation = operation_match.group(1) if operation_match else "count"
            column = next((h for h in headers if re.search(
                r"\b" + re.escape(h.lower()) + r"\b", lower)), None)
            if column is None:
                numeric_columns = table.get("numeric_columns", [])
                if len(numeric_columns) == 1:
                    column = numeric_columns[0]
            if operation == "count" and re.search(r"\b(count|number of)\s+(rows?|records?)\b", lower):
                return self._graph("table_row_count", text, {"table": table})
            if column:
                return self._graph("table_stat", text, {
                    "table": table, "column": column, "operation": operation
                })
        return None

    @staticmethod
    def _expression(text):
        candidate = re.sub(r"^(?:please\s+)?(?:calculate|compute|evaluate|what is|what's)\s+",
                           "", text.strip(), flags=re.IGNORECASE)
        candidate = candidate.rstrip("?= ").strip()
        if _EXPR.fullmatch(candidate) and re.search(r"[+*/%()]|\d\s*-\s*\d", candidate):
            return candidate
        return None

    @staticmethod
    def _number_list(text):
        match = re.search(r"\b(?:average|mean|median|mode|variance|standard deviation|stdev|"
                          r"minimum|min|maximum|max|range|percentile|statistics|stats|"
                          r"sum|total|add|plus|count|gcd|lcm|greatest common divisor|least common multiple)"
                          r"\b(?:\s+of)?\s+(.+)$",
                          text.strip(), re.IGNORECASE)
        if not match:
            return None
        candidate = match.group(1)
        return candidate if _NUMBER_LIST.fullmatch(candidate) else None

    @staticmethod
    def _graph(kind, goal, inputs):
        return ClassifiedTask(kind, goal, inputs)

