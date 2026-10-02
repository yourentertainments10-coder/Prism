"""Read-only local catalogue import; no remote service or model is contacted."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from prism_superagent.api_registry.catalog import SOURCE_REPOSITORY, parse_catalog

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT / "public-apis"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data" / "api_catalog.json"


def import_catalogue(
    source=DEFAULT_SOURCE, output=DEFAULT_OUTPUT, source_commit=None, imported_at=None
):
    source = Path(source).resolve()
    readme = source / "README.md"
    if not readme.is_file():
        raise FileNotFoundError(f"Catalogue README not found: {readme}")
    try:
        observed_commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "-C", str(source), "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            "Catalogue source must be a Git checkout with a readable origin and commit."
        ) from exc
    parsed_remote = urlparse(remote.replace("git@github.com:", "https://github.com/"))
    remote_path = parsed_remote.path.strip("/").removesuffix(".git").casefold()
    if (
        parsed_remote.hostname != "github.com"
        or remote_path != "public-apis/public-apis"
    ):
        raise ValueError("Catalogue checkout origin is not public-apis/public-apis.")
    if source_commit is not None and source_commit != observed_commit:
        raise ValueError(
            "Requested source commit does not match the local checkout HEAD."
        )
    source_commit = observed_commit
    markdown_bytes = readme.read_bytes()
    markdown = markdown_bytes.decode("utf-8-sig")
    imported_at = imported_at or datetime.now(timezone.utc).isoformat()
    parsed = parse_catalog(
        markdown, source_commit=source_commit, imported_at=imported_at
    )
    document = {
        "schema_version": 1,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "local_path": _relative_source_path(source),
            "commit": source_commit,
            "readme_sha256": hashlib.sha256(markdown_bytes).hexdigest(),
            "imported_at": imported_at,
        },
        "counts": {
            "entries": len(parsed.entries),
            "categories": len(parsed.categories),
            "parse_issues": len(parsed.issues),
        },
        "categories": list(parsed.categories),
        "issues": list(parsed.issues),
        "entries": [entry.to_dict() for entry in parsed.entries],
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=output.name + ".", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(encoded)
            temp_name = temporary.name
        Path(temp_name).replace(output)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
    return document


def _relative_source_path(source):
    try:
        return source.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Import the local public-apis README into Prism's catalogue."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-commit")
    args = parser.parse_args(argv)
    document = import_catalogue(args.source, args.output, args.source_commit)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                **document["counts"],
                "source_commit": document["source"]["commit"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
