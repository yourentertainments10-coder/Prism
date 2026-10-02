"""Offline parser for the public-apis README catalogue tables."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from prism_superagent.api_registry.models import CatalogEntry

SOURCE_REPOSITORY = "https://github.com/public-apis/public-apis"
_EXPECTED_HEADERS = ("api", "description", "auth", "https", "cors")
_MARKDOWN_LINK = re.compile(r"^\[([^\]]+)\]\((.+)\)$", re.DOTALL)


@dataclass(frozen=True)
class CatalogParseResult:
    entries: tuple[CatalogEntry, ...]
    categories: tuple[str, ...]
    issues: tuple[dict, ...]


def normalize_auth(raw):
    value = _unbacktick(raw).strip()
    folded = value.casefold()
    if folded in ("no", "none", "null", ""):
        return "none"
    if folded in ("unknown", "n/a"):
        return "unknown"
    if "oauth" in folded:
        return "oauth"
    if "apikey" in folded.replace("_", "").replace("-", "") or "api key" in folded:
        return "api_key"
    return "other"


def normalize_yes_no(raw):
    value = _unbacktick(raw).strip().casefold()
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def parse_catalog(
    markdown, source_commit, imported_at=None, source_repository=SOURCE_REPOSITORY
):
    """Parse only category-scoped API/Description/Auth/HTTPS/CORS tables.

    Malformed catalogue rows are reported and skipped so one editorial issue
    cannot discard the remaining local source. Duplicate display names remain
    separate entries; identity includes category and documentation URL.
    """
    if not source_commit or not isinstance(source_commit, str):
        raise ValueError("An exact source Git commit is required for catalogue import.")
    imported_at = imported_at or datetime.now(timezone.utc).isoformat()
    lines = markdown.splitlines()
    entries, categories, issues = [], [], []
    category = None
    in_catalog_table = False
    seen_ids = set()

    for line_number, line in enumerate(lines, 1):
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            category = heading.group(1).strip()
            in_catalog_table = False
            continue
        if re.match(r"^##\s+", line):
            category = None
            in_catalog_table = False
            continue
        if category and _is_catalog_header(line):
            in_catalog_table = True
            if category not in categories:
                categories.append(category)
            continue
        if not in_catalog_table:
            continue

        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            if stripped.startswith("**[") or re.match(r"^#{1,6}\s", stripped):
                in_catalog_table = False
            continue
        cells = _split_markdown_row(stripped)
        while len(cells) > 5 and cells[-1] == "":
            cells.pop()
        if cells and all(
            re.fullmatch(r":?-{3,}:?", item.replace(" ", "")) for item in cells
        ):
            continue
        if not cells or not cells[0].startswith("["):
            issues.append({"line": line_number, "reason": "row is not an API link"})
            continue
        if len(cells) < 5:
            issues.append(
                {"line": line_number, "reason": f"expected 5 cells, found {len(cells)}"}
            )
            continue
        extra_cells = tuple(cells[5:])
        if extra_cells:
            issues.append(
                {
                    "line": line_number,
                    "reason": f"extra cells preserved outside the 5-column schema: {extra_cells!r}",
                }
            )
        link = _MARKDOWN_LINK.fullmatch(cells[0].strip())
        if not link:
            issues.append(
                {"line": line_number, "reason": "API name is not a Markdown link"}
            )
            continue
        name, docs_url = link.groups()
        name, docs_url = name.strip(), docs_url.strip()
        description = cells[1].strip()
        if not name or not docs_url or not description:
            issues.append(
                {
                    "line": line_number,
                    "reason": "name, link, and description are required",
                }
            )
            continue
        identity = f"{category}\0{name.casefold()}\0{docs_url}"
        suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        slug = (
            re.sub(
                r"[^a-z0-9]+",
                "-",
                unicodedata.normalize("NFKD", name)
                .encode("ascii", "ignore")
                .decode("ascii")
                .casefold(),
            ).strip("-")
            or "api"
        )
        entry_id = f"{slug}-{suffix}"
        if entry_id in seen_ids:
            issues.append(
                {"line": line_number, "reason": "duplicate category/name/link row"}
            )
            continue
        seen_ids.add(entry_id)
        auth_raw, https_raw, cors_raw = (cell.strip() for cell in cells[2:5])
        entries.append(
            CatalogEntry(
                entry_id=entry_id,
                name=name,
                category=category,
                description=description,
                auth_raw=auth_raw,
                auth=normalize_auth(auth_raw),
                https_raw=https_raw,
                https=normalize_yes_no(https_raw),
                cors_raw=cors_raw,
                cors=normalize_yes_no(cors_raw),
                documentation_url=docs_url,
                source_repository=source_repository,
                source_commit=source_commit,
                imported_at=imported_at,
                raw_extra_cells=extra_cells,
            )
        )
    return CatalogParseResult(tuple(entries), tuple(categories), tuple(issues))


def _is_catalog_header(line):
    cells = [cell.strip().casefold() for cell in _split_markdown_row(line.strip())]
    return tuple(cells) == _EXPECTED_HEADERS


def _split_markdown_row(line):
    text = line.strip()
    text = text.removeprefix("|")
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells, current, in_code, escaped = [], [], False, False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "`":
            in_code = not in_code
            current.append(char)
        elif char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def _unbacktick(value):
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value
