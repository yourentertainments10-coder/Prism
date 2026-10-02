"""Structured JSON/XML/SQL processing over in-memory or attached data."""

import json
import re
import sqlite3
from decimal import Decimal, InvalidOperation

from prism_superagent.engine.tabular import attached_tables


def classify_data_request(content):
    if not isinstance(content, str):
        return None
    request = _without_attachments(content)
    lower = request.lower()
    if re.search(r"\b(sql query|run sql|execute sql|query this data)\b", lower) or \
            re.match(r"\s*(select|with)\b", lower):
        match = re.search(r"\b(select|with)\b[\s\S]*?(?:```|$)", request, re.IGNORECASE)
        query = match.group(0).replace("```", "").strip() if match else None
        if query:
            tables = attached_tables(content)
            return "sql_query", {"query": query, "tables": tables}
    return None


def execute_data(operation, inputs):
    if operation == "sql_query":
        return _execute_readonly_sql(inputs["query"], inputs.get("tables", []))
    raise ValueError(f"Unsupported structured data operation: {operation}")


def _execute_readonly_sql(query, tables):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        names = set()
        for index, table in enumerate(tables):
            original = table.get("filename", "data").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            candidate = re.sub(r"\W+", "_", original.rsplit(".", 1)[0]).strip("_").lower() or "data"
            if candidate[0].isdigit():
                candidate = "t_" + candidate
            if candidate in names or candidate == "data":
                candidate = f"table_{index + 1}"
            names.add(candidate)
            _create_table(connection, candidate, table)
            if index == 0:
                _create_table(connection, "data", table)
                names.add("data")
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_sql_authorizer)
        cursor = connection.execute(query)
        fetched = cursor.fetchmany(501)
        rows = [dict(row) for row in fetched[:500]]
        return {"columns": [item[0] for item in cursor.description or []],
                "rows": rows, "truncated": len(fetched) > 500,
                "tables": ["data"] + sorted(names - {"data"}) if tables else []}
    finally:
        connection.close()


def _create_table(connection, name, table):
    quote = lambda value: '"' + value.replace('"', '""') + '"'
    columns = table["headers"]
    if not columns:
        raise ValueError("The attached table has no columns.")
    connection.execute(f"CREATE TABLE {quote(name)} ({', '.join(quote(c) for c in columns)})")
    values = []
    for row in table["records"]:
        values.append(tuple(_sql_value(row.get(column, "")) for column in columns))
    marks = ",".join("?" for _ in columns)
    connection.executemany(f"INSERT INTO {quote(name)} VALUES ({marks})", values)


def _sql_value(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = Decimal(text.replace(",", ""))
        return int(number) if number == number.to_integral_value() else float(number)
    except InvalidOperation:
        return text


def _sql_authorizer(action, arg1, arg2, database, trigger):
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
               getattr(sqlite3, "SQLITE_RECURSIVE", -1)}
    if action in allowed:
        if action == sqlite3.SQLITE_FUNCTION:
            function_name = (arg2 or arg1 or "").lower()
            deterministic = {"abs", "avg", "char", "coalesce", "count", "glob", "group_concat",
                             "hex", "ifnull", "instr", "length", "like", "likelihood", "lower",
                             "ltrim", "max", "min", "nullif", "quote", "replace", "round", "rtrim",
                             "substr", "sum", "total", "trim", "typeof", "unicode", "upper"}
            if function_name not in deterministic:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _without_attachments(content):
    return re.sub(r"\[Attached file: [^\]]+\]\s*```[^\n]*\n[\s\S]*?```", " ", content,
                  flags=re.IGNORECASE)

