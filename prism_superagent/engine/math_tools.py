"""Deterministic math, statistics, unit and calendar operations."""

import calendar
import math
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import mean, median, multimode, pstdev, pvariance, stdev, variance

_FACTORS = {
    "mm": ("length", Decimal("0.001")), "millimeter": ("length", Decimal("0.001")),
    "millimeters": ("length", Decimal("0.001")), "cm": ("length", Decimal("0.01")),
    "centimeter": ("length", Decimal("0.01")), "centimeters": ("length", Decimal("0.01")),
    "m": ("length", Decimal(1)), "meter": ("length", Decimal(1)), "meters": ("length", Decimal(1)),
    "km": ("length", Decimal(1000)), "kilometer": ("length", Decimal(1000)),
    "kilometers": ("length", Decimal(1000)), "in": ("length", Decimal("0.0254")),
    "inch": ("length", Decimal("0.0254")), "inches": ("length", Decimal("0.0254")),
    "ft": ("length", Decimal("0.3048")), "foot": ("length", Decimal("0.3048")),
    "feet": ("length", Decimal("0.3048")), "yd": ("length", Decimal("0.9144")),
    "mile": ("length", Decimal("1609.344")), "miles": ("length", Decimal("1609.344")),
    "g": ("mass", Decimal("0.001")), "gram": ("mass", Decimal("0.001")),
    "grams": ("mass", Decimal("0.001")), "kg": ("mass", Decimal(1)),
    "kilogram": ("mass", Decimal(1)), "kilograms": ("mass", Decimal(1)),
    "lb": ("mass", Decimal("0.45359237")), "lbs": ("mass", Decimal("0.45359237")),
    "pound": ("mass", Decimal("0.45359237")), "pounds": ("mass", Decimal("0.45359237")),
    "oz": ("mass", Decimal("0.028349523125")), "ounce": ("mass", Decimal("0.028349523125")),
    "ounces": ("mass", Decimal("0.028349523125")), "ml": ("volume", Decimal("0.001")),
    "milliliter": ("volume", Decimal("0.001")), "l": ("volume", Decimal(1)),
    "liter": ("volume", Decimal(1)), "liters": ("volume", Decimal(1)),
    "min": ("time", Decimal(60)), "minute": ("time", Decimal(60)),
    "minutes": ("time", Decimal(60)), "h": ("time", Decimal(3600)),
    "hr": ("time", Decimal(3600)), "hour": ("time", Decimal(3600)),
    "hours": ("time", Decimal(3600)), "day": ("time", Decimal(86400)),
    "days": ("time", Decimal(86400)), "s": ("time", Decimal(1)),
    "sec": ("time", Decimal(1)), "second": ("time", Decimal(1)),
    "seconds": ("time", Decimal(1)), "mb": ("data", Decimal(1000**2)),
    "gb": ("data", Decimal(1000**3)), "kb": ("data", Decimal(1000)),
    "mib": ("data", Decimal(1024**2)), "gib": ("data", Decimal(1024**3)),
    "kib": ("data", Decimal(1024)), "byte": ("data", Decimal(1)),
    "bytes": ("data", Decimal(1)),
}
_CONVERT = re.compile(
    r"(?:convert|conversion|in)\s+([-+]?\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s+(?:to|in)\s+([a-zA-Z]+)",
    re.IGNORECASE,
)
_DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"


def classify_math_request(text, number_list):
    lower = text.lower()
    named_temperature = re.search(
        r"convert\s+([-+]?\d+(?:\.\d+)?)\s*(?:degrees?\s*)?(celsius|fahrenheit|[cf])\s+to\s*(?:degrees?\s*)?(celsius|fahrenheit|[cf])\b",
        text, re.IGNORECASE)
    if named_temperature:
        value, source, target = named_temperature.groups()
        scale = lambda unit: "C" if unit.lower() in ("c", "celsius") else "F"
        return "temperature_conversion", {"value": Decimal(value), "source": scale(source),
                                           "target": scale(target)}
    percentage = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%\s*of\s*([-+]?\d+(?:\.\d+)?)", text, re.I)
    if percentage:
        return "percentage", {"percent": Decimal(percentage.group(1)),
                              "value": Decimal(percentage.group(2))}
    change = re.search(r"percent change from\s+([-+]?\d+(?:\.\d+)?)\s+to\s+([-+]?\d+(?:\.\d+)?)", text, re.I)
    if change:
        return "percent_change", {"start": Decimal(change.group(1)), "end": Decimal(change.group(2))}
    factorial = re.search(r"factorial of\s+(\d+)\b", text, re.I)
    if factorial:
        return "factorial", {"value": int(factorial.group(1))}
    square_root = re.search(r"(?:square root|sqrt) of\s+([-+]?\d+(?:\.\d+)?)", text, re.I)
    if square_root:
        return "square_root", {"value": Decimal(square_root.group(1))}
    integer_operation = re.search(r"\b(gcd|greatest common divisor|lcm|least common multiple)\b", lower)
    if integer_operation and number_list and all(
            value == value.to_integral_value() for value in number_list):
        operation = "gcd" if integer_operation.group(1) in ("gcd", "greatest common divisor") else "lcm"
        return operation, {"values": [int(value) for value in number_list]}
    temp = re.search(r"convert\s+([-+]?\d+(?:\.\d+)?)\s*°?\s*([cf])\s+to\s+°?\s*([cf])\b",
                     text, re.IGNORECASE)
    if temp:
        value, source, target = temp.groups()
        return "temperature_conversion", {"value": Decimal(value), "source": source.upper(),
                                           "target": target.upper()}
    convert = _CONVERT.search(text)
    if convert:
        value, source, target = convert.groups()
        return "unit_conversion", {"value": Decimal(value), "source": source.lower(),
                                    "target": target.lower()}
    if "between" in lower and "day" in lower:
        match = re.search(rf"between\s+({_DATE})\s+and\s+({_DATE})", text, re.IGNORECASE)
        if match:
            return "date_difference", {"start": match.group(1), "end": match.group(2)}
    add = re.search(rf"(?:add|after)\s+(\d+)\s+(days?|weeks?)\s+to\s+({_DATE})", text, re.I)
    if add:
        return "date_add", {"date": add.group(3), "amount": int(add.group(1)),
                             "unit": add.group(2).lower()}
    after = re.search(rf"(\d+)\s+(days?|weeks?)\s+(after|before)\s+({_DATE})", text, re.I)
    if after:
        amount = int(after.group(1)) * (7 if after.group(2).lower().startswith("week") else 1)
        if after.group(3).lower() == "before":
            amount = -amount
        return "date_add", {"date": after.group(4), "amount": amount, "unit": "days"}
    month_add = re.search(rf"(?:add|after)\s+(\d+)\s+months?\s+to\s+({_DATE})", text, re.I)
    if month_add:
        return "date_add_months", {"date": month_add.group(2), "amount": int(month_add.group(1))}
    stat_match = re.search(r"\b(mean|average|median|mode|variance|standard deviation|stdev|"
                           r"minimum|min|maximum|max|range|percentile|statistics|stats|count)\b", lower)
    if number_list and stat_match:
        operation = stat_match.group(1)
        if operation in ("statistics", "stats"):
            operation = "summary"
        percentile = re.search(r"(\d+(?:\.\d+)?)\s*(?:st|nd|rd|th)?\s*percentile", lower)
        return "statistics", {"values": number_list, "operation": operation,
                              "percentile": float(percentile.group(1)) if percentile else 50}
    return None


def execute_math(kind, inputs):
    if kind == "percentage":
        return {"value": inputs["value"] * inputs["percent"] / Decimal(100),
                "percent": inputs["percent"], "base": inputs["value"]}
    if kind == "percent_change":
        if inputs["start"] == 0:
            raise ValueError("Percent change from zero is undefined.")
        return {"value": (inputs["end"] - inputs["start"]) / abs(inputs["start"]) * Decimal(100),
                "start": inputs["start"], "end": inputs["end"]}
    if kind == "factorial":
        value = inputs["value"]
        if value > 5000:
            raise ValueError("Factorial is limited to values at or below 5000.")
        return {"value": math.factorial(value)}
    if kind == "square_root":
        if inputs["value"] < 0:
            raise ValueError("A real square root is not defined for a negative number.")
        return {"value": inputs["value"].sqrt()}
    if kind == "gcd":
        return {"value": math.gcd(*inputs["values"])}
    if kind == "lcm":
        return {"value": math.lcm(*inputs["values"])}
    if kind == "statistics":
        values = inputs["values"]
        op = inputs["operation"]
        if not values:
            raise ValueError("Provide at least one number.")
        if op in ("mean", "average"):
            value = mean(values)
        elif op == "median":
            value = median(values)
        elif op == "mode":
            modes = multimode(values)
            value = modes[0] if len(modes) == 1 else modes
        elif op == "variance":
            value = pvariance(values) if len(values) == 1 else variance(values)
        elif op in ("standard deviation", "stdev"):
            value = pstdev(values) if len(values) == 1 else stdev(values)
        elif op in ("minimum", "min"):
            value = min(values)
        elif op in ("maximum", "max"):
            value = max(values)
        elif op == "range":
            value = max(values) - min(values)
        elif op == "percentile":
            value = _percentile(values, inputs.get("percentile", 50))
        elif op == "count":
            value = len(values)
        else:
            value = {"count": len(values), "mean": mean(values), "median": median(values),
                     "min": min(values), "max": max(values), "range": max(values)-min(values),
                     "population_stddev": pstdev(values)}
        return {"value": value, "count": len(values), "operation": op}
    if kind in ("unit_conversion", "temperature_conversion"):
        value = inputs["value"]
        source, target = inputs["source"], inputs["target"]
        if kind == "temperature_conversion":
            celsius = value if source == "C" else (value - 32) * Decimal(5) / Decimal(9)
            result = celsius if target == "C" else celsius * Decimal(9) / Decimal(5) + 32
        else:
            if source not in _FACTORS or target not in _FACTORS:
                raise ValueError("That unit is not supported by Prism's converter.")
            source_type, source_factor = _FACTORS[source]
            target_type, target_factor = _FACTORS[target]
            if source_type != target_type:
                raise ValueError("Those units measure different quantities.")
            result = value * source_factor / target_factor
        return {"value": result, "source": source, "target": target}
    if kind == "date_difference":
        first, second = _parse_date(inputs["start"]), _parse_date(inputs["end"])
        return {"days": (second - first).days, "start": first.isoformat(), "end": second.isoformat()}
    if kind == "date_add":
        day = _parse_date(inputs["date"])
        amount = inputs["amount"] * (7 if inputs["unit"].startswith("week") else 1)
        return {"date": (day + timedelta(days=amount)).isoformat()}
    if kind == "date_add_months":
        day = _parse_date(inputs["date"])
        month_index = day.year * 12 + day.month - 1 + inputs["amount"]
        year, month0 = divmod(month_index, 12)
        month = month0 + 1
        return {"date": date(year, month, min(day.day, calendar.monthrange(year, month)[1])).isoformat()}
    raise ValueError(f"Unsupported math task: {kind}")


def _parse_date(value):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Could not parse date '{value}'. Use YYYY-MM-DD or MM/DD/YYYY.")


def _percentile(values, percentile):
    if not 0 <= percentile <= 100:
        raise ValueError("Percentile must be between 0 and 100.")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * Decimal(str(percentile)) / Decimal(100)
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - Decimal(lower))

