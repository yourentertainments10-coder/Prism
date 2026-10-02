"""Parse CSV-like text attached by Prism and expose bounded table helpers."""

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

_ATTACHMENT = re.compile(
    r"\[Attached file: ([^\]]+)\]\s*```[^\n]*\n([\s\S]*?)```", re.IGNORECASE
)
_SHEET = re.compile(r"^\[Sheet: ([^\]]+)\]\s*$", re.MULTILINE)


def attached_tables(content):
    tables = []
    for match in _ATTACHMENT.finditer(content):
        filename, body = match.groups()
        if not filename.lower().endswith((".csv", ".tsv", ".xlsx")):
            continue
        segments = _SHEET.split(body)
        if len(segments) > 1:
            chunks = [(segments[i].strip(), segments[i + 1])
                      for i in range(1, len(segments), 2)]
            prefix = segments[0].strip()
            if prefix:
                chunks.insert(0, ("Sheet 1", prefix))
        else:
            chunks = [(filename, body)]
        for sheet_name, raw in chunks:
            table = _parse_table(raw, filename, sheet_name)
            if table:
                tables.append(table)
    return tables


def _parse_table(raw, filename, sheet_name):
    sample = raw[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample and "," not in sample else csv.excel
    rows = list(csv.reader(io.StringIO(raw), dialect))
    rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2 or len(rows[0]) < 2:
        return None
    headers = rows[0]
    records = [dict(zip(headers, row)) for row in rows[1:] if len(row) == len(headers)]
    if not records:
        return None
    numeric_columns = []
    for header in headers:
        values = [_to_decimal(row.get(header, "")) for row in records]
        if any(v is not None for v in values) and all(
                v is not None or not row.get(header, "").strip()
                for v, row in zip(values, records)):
            numeric_columns.append(header)
    return {"filename": filename, "sheet": sheet_name, "headers": headers,
            "records": records, "numeric_columns": numeric_columns}


def _to_decimal(value):
    text = str(value or "").strip().replace(",", "")
    text = re.sub(r"^(?:\$|€|£|₹|USD\s*|INR\s*)", "", text, flags=re.IGNORECASE)
    text = text.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def monthly_sales_columns(table):
    date_column = next((h for h in table["headers"]
                        if re.search(r"date|period|time|(^|[\s_-])month($|[\s_-])", h,
                                     re.IGNORECASE)
                        and h not in table["numeric_columns"]
                        and any(_month_value(row.get(h, "")) for row in table["records"])), None)
    value_column = next((h for h in table["headers"]
                         if re.search(r"sales|revenue|amount|total", h, re.IGNORECASE)
                         and h in table["numeric_columns"]), None)
    if date_column and value_column:
        return date_column, value_column
    return None


def _month_value(value):
    text = str(value or "").strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m",
                "%m/%Y", "%b %Y", "%B %Y", "%b-%Y", "%B-%Y"):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            pass
    return False


def decimal_value(value):
    return _to_decimal(value)

