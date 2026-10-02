"""Allowlisted deterministic operations; models never supply executable code."""

import ast
import operator
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, DivisionByZero

from prism_superagent.engine.data_tools import execute_data
from prism_superagent.engine.documents import execute_document
from prism_superagent.engine.math_tools import execute_math
from prism_superagent.engine.tabular import decimal_value
from prism_superagent.engine.web_retrieval import execute_web

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
           ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate_expression(expression):
    tree = ast.parse(expression, mode="eval")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (right != right.to_integral_value() or abs(right) > 100):
                raise ValueError("Exponent must be an integer between -100 and 100.")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](visit(node.operand))
        raise ValueError("Expression contains an unsupported operation.")

    try:
        return visit(tree)
    except (DivisionByZero, ZeroDivisionError):
        raise ValueError("Division by zero is undefined.") from None


def execute_operation(operation, inputs):
    if operation == "calculate_mean":
        values = inputs["values"]
        return {"value": sum(values, Decimal(0)) / Decimal(len(values)), "count": len(values)}
    if operation == "calculate_sum":
        return {"value": sum(inputs["values"], Decimal(0)), "count": len(inputs["values"])}
    if operation == "evaluate_expression":
        return {"value": evaluate_expression(inputs["expression"])}
    if operation in ("statistics", "percentage", "percent_change", "factorial", "square_root", "gcd", "lcm",
                     "unit_conversion", "temperature_conversion", "date_difference", "date_add", "date_add_months"):
        return execute_math(operation, inputs)
    if operation in ("document_extract", "document_compare", "table_extract", "csv_to_json", "json_format",
                     "json_query", "xml_format", "xml_query", "ocr_images"):
        return execute_document(operation, inputs)
    if operation == "sql_query":
        return execute_data(operation, inputs)
    if operation in ("web_api_get", "web_search", "source_verify"):
        return execute_web(operation, inputs)
    if operation == "table_sort":
        table, column = inputs["table"], inputs["column"]
        values = sorted(table["records"], key=lambda row: _sort_value(row.get(column, "")),
                        reverse=inputs.get("descending", False))
        return {"headers": table["headers"], "rows": values[:500],
                "row_count": len(values), "column": column}
    if operation == "table_filter":
        table, column = inputs["table"], inputs["column"]
        expected = str(inputs["value"]).casefold()
        rows = [row for row in table["records"]
                if str(row.get(column, "")).casefold() == expected]
        return {"headers": table["headers"], "rows": rows[:500],
                "row_count": len(rows), "column": column}
    if operation == "table_deduplicate":
        table = inputs["table"]
        seen, rows = set(), []
        for row in table["records"]:
            key = tuple(row.get(header, "") for header in table["headers"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
        return {"headers": table["headers"], "rows": rows[:500],
                "row_count": len(rows), "removed": len(table["records"]) - len(rows)}
    if operation == "table_row_count":
        return {"count": len(inputs["table"]["records"])}
    if operation in ("parse_table", "aggregate_monthly", "calculate_stat"):
        if operation == "parse_table":
            return inputs["table"]
        if operation == "aggregate_monthly":
            table = inputs["table"]
            date_col, value_col = inputs["date_column"], inputs["value_column"]
            totals = defaultdict(Decimal)
            included = 0
            for row in table["records"]:
                month = _month_key(row.get(date_col, ""))
                amount = decimal_value(row.get(value_col, ""))
                if month and amount is not None:
                    totals[month] += amount
                    included += 1
            if not included:
                raise ValueError("No rows had both a readable date and numeric sales value.")
            return {"monthly_totals": dict(sorted(totals.items())), "rows_included": included,
                    "overall_total": sum(totals.values(), Decimal(0)),
                    "value_column": value_col, "date_column": date_col,
                    "source_rows": len(table["records"])}
    raise ValueError(f"Unsupported deterministic operation: {operation}")


def calculate_table_stat(table, column, operation):
    values = [decimal_value(row.get(column, "")) for row in table["records"]]
    values = [value for value in values if value is not None]
    if not values:
        raise ValueError(f"Column '{column}' has no numeric values.")
    if operation in ("mean", "average"):
        from statistics import mean
        value = mean(values)
    elif operation == "median":
        from statistics import median
        value = median(values)
    elif operation == "mode":
        from statistics import multimode
        modes = multimode(values)
        value = modes[0] if len(modes) == 1 else modes
    elif operation == "variance":
        from statistics import variance, pvariance
        value = variance(values) if len(values) > 1 else pvariance(values)
    elif operation in ("standard deviation", "stdev"):
        from statistics import stdev, pstdev
        value = stdev(values) if len(values) > 1 else pstdev(values)
    elif operation in ("minimum", "min"):
        value = min(values)
    elif operation in ("maximum", "max"):
        value = max(values)
    elif operation == "range":
        value = max(values) - min(values)
    elif operation in ("sum", "total"):
        value = sum(values, Decimal(0))
    else:
        value = len(values)
    return {"value": value if isinstance(value, list) else Decimal(value), "count": len(values)}


def _sort_value(value):
    number = decimal_value(value)
    return (0, number) if number is not None else (1, str(value).casefold())


def _month_key(value):
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m")
    except ValueError:
        pass
    for parser in (date.fromisoformat,):
        try:
            return parser(text).strftime("%Y-%m")
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m", "%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    match = re.match(r"^(\d{4})[-/](\d{1,2})$", text)
    if match and 1 <= int(match.group(2)) <= 12:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    return None

