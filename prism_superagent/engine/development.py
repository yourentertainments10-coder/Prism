"""Workspace-confined Git, Python inspection, lint, test and patch workflows."""

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

_SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache"}


class DevelopmentTools:
    def __init__(self, workspace, timeout=120, output_limit=20_000):
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout
        self.output_limit = output_limit

    def execute(self, operation, inputs):
        if operation == "git_status":
            return self._git(["status", "--short", "--branch"])
        if operation == "git_diff":
            return self._git(["diff", "--no-ext-diff", "--no-textconv", "--", "."])
        if operation == "project_inspect":
            return self._inspect()
        if operation in ("python_ast", "python_compile", "python_lint"):
            files = self._python_files(inputs.get("path"))
            return self._analyze_python(files, operation)
        if operation == "compiler_check":
            return self._compile_c_family(inputs)
        if operation == "run_tests":
            return self._run_tests()
        if operation == "patch_test_verify":
            return self._patch_test_verify(inputs["patch"])
        raise ValueError(f"Unsupported development operation: {operation}")

    def _git(self, args):
        if not (self.workspace / ".git").exists():
            return {"text": "The configured Prism workspace is not a Git repository.", "ok": False}
        try:
            result = subprocess.run(["git", *args], cwd=self.workspace, shell=False,
                                    capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"text": f"Git could not complete: {exc}", "ok": False}
        return {"text": (result.stdout + result.stderr)[:self.output_limit],
                "ok": result.returncode == 0, "returncode": result.returncode}

    def _files(self):
        found = []
        for current, dirs, files in os.walk(self.workspace, followlinks=False):
            dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not name.startswith(".")]
            for filename in files:
                path = Path(current, filename)
                if path.is_symlink():
                    continue
                found.append(path)
                if len(found) >= 5000:
                    return found
        return found

    def _inspect(self):
        files = self._files()
        by_ext = {}
        for path in files:
            ext = path.suffix.lower() or "[no extension]"
            by_ext[ext] = by_ext.get(ext, 0) + 1
        listing = [path.relative_to(self.workspace).as_posix() for path in files[:200]]
        return {"file_count": len(files), "truncated": len(files) >= 5000,
                "by_extension": dict(sorted(by_ext.items())), "files": listing}

    def _python_files(self, target=None):
        if target:
            relative = PurePosixPath(str(target).replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Project paths must remain inside the configured workspace.")
            path = (self.workspace / Path(*relative.parts)).resolve()
            if path != self.workspace and self.workspace not in path.parents:
                raise ValueError("Project paths must remain inside the configured workspace.")
            if path.is_file():
                if path.suffix.lower() != ".py":
                    raise ValueError("This deterministic analyzer currently accepts Python files.")
                return [path]
            root = path
        else:
            root = self.workspace
        return [path for path in self._files() if path.suffix.lower() == ".py"
                and (path == root or root in path.parents)][:500]

    def _analyze_python(self, files, operation):
        if operation == "python_lint" and importlib.util.find_spec("ruff"):
            target = str(files[0]) if len(files) == 1 else str(self.workspace)
            try:
                result = subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", target],
                                        cwd=self.workspace, shell=False, capture_output=True,
                                        text=True, timeout=self.timeout)
                return {"files_checked": len(files), "errors": [],
                        "warnings": (result.stdout + result.stderr).splitlines()[:200],
                        "ok": result.returncode == 0, "text": (result.stdout + result.stderr)[:self.output_limit]}
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {"files_checked": len(files), "errors": [],
                        "warnings": [f"Ruff could not complete: {exc}"], "ok": False}
        errors, summaries, warnings = [], [], []
        for path in files:
            try:
                if path.stat().st_size > 1_000_000:
                    warnings.append(f"Skipped large file: {path.relative_to(self.workspace)}")
                    continue
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
                compile(tree, str(path), "exec")
                if operation == "python_ast":
                    summaries.append({"file": path.relative_to(self.workspace).as_posix(),
                                      "functions": [n.name for n in ast.walk(tree)
                                                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                                      "classes": [n.name for n in ast.walk(tree)
                                                  if isinstance(n, ast.ClassDef)],
                                      "imports": sorted({n.module or "" for n in ast.walk(tree)
                                                         if isinstance(n, ast.ImportFrom)} |
                                                        {alias.name for n in ast.walk(tree)
                                                         if isinstance(n, ast.Import)
                                                         for alias in n.names})})
                if operation == "python_lint":
                    for number, line in enumerate(source.splitlines(), 1):
                        if line.rstrip(" \t") != line:
                            warnings.append(f"{path.relative_to(self.workspace)}:{number}: trailing whitespace")
                        if len(line) > 120:
                            warnings.append(f"{path.relative_to(self.workspace)}:{number}: line exceeds 120 characters")
            except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
                errors.append({"file": path.relative_to(self.workspace).as_posix(),
                               "error": f"{type(exc).__name__}: {exc}"})
        result = {"files_checked": len(files), "errors": errors, "warnings": warnings[:200]}
        if summaries:
            result["modules"] = summaries[:200]
        result["ok"] = not errors and (operation != "python_lint" or not warnings)
        return result

    def _run_tests(self):
        files = self._files()
        test_files = [p for p in files if p.suffix.lower() == ".py" and
                      (p.name.startswith("test_") or p.name.endswith("_test.py"))]
        if not test_files:
            return {"ok": True, "tests_found": False,
                    "text": "No Python test files were found in the configured workspace."}
        uses_pytest = any(re.search(r"\bpytest\b|\bdef\s+test_", p.read_text(encoding="utf-8", errors="replace"))
                          for p in test_files)
        if importlib.util.find_spec("pytest"):
            command = [sys.executable, "-m", "pytest", "-q", "--disable-warnings", "--maxfail=1"]
        elif uses_pytest:
            return {"ok": False, "text": "pytest-style tests were found, but pytest is not installed."}
        else:
            command = [sys.executable, "-m", "unittest", "discover", "-v"]
        try:
            result = subprocess.run(command, cwd=self.workspace, shell=False,
                                    capture_output=True, text=True, timeout=self.timeout)
            return {"ok": result.returncode == 0,
                    "returncode": result.returncode,
                    "text": (result.stdout + result.stderr)[-self.output_limit:],
                    "command": Path(command[0]).name}
        except subprocess.TimeoutExpired:
            return {"ok": False, "text": f"Test execution timed out after {self.timeout} seconds."}
        except OSError as exc:
            return {"ok": False, "text": f"Tests could not run: {exc}"}

    def _compile_c_family(self, inputs):
        sources = inputs.get("sources", [])
        paths = []
        if inputs.get("path"):
            relative = PurePosixPath(str(inputs["path"]).replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Compiler paths must remain inside the configured workspace.")
            target = (self.workspace / Path(*relative.parts)).resolve()
            if self.workspace not in target.parents or not target.is_file():
                raise ValueError("Compiler target must be an existing file inside the workspace.")
            paths.append(target)
            sources = [{"filename": target.name, "text": target.read_text(encoding="utf-8")}]
        if not sources:
            return {"ok": False, "files_checked": 0, "text": "No C or C++ source was provided."}
        outputs = []
        for source in sources[:20]:
            filename = source["filename"]
            suffix = Path(filename).suffix.lower()
            is_cpp = suffix in (".cpp", ".cc", ".cxx", ".hpp")
            candidates = ([("g++", "c++"), ("clang++", "c++"), ("cl", "cpp")] if is_cpp else
                          [("gcc", "c"), ("clang", "c"), ("cl", "c")])
            compiler = next(((shutil.which(name), language) for name, language in candidates
                             if shutil.which(name)), None)
            if not compiler:
                return {"ok": False, "files_checked": len(outputs),
                        "text": f"No C/C++ compiler is installed to check {filename}."}
            executable, language = compiler
            if Path(executable).name.lower() == "cl.exe":
                if "text" in source:
                    return {"ok": False, "files_checked": len(outputs),
                            "text": "MSVC cannot compile an attached source without writing a temporary file; install GCC or Clang for this route."}
                command = [executable, "/nologo", "/Zs", "/TP" if is_cpp else "/TC", str(source["path"])]
                input_text = None
            elif "text" in source:
                command = [executable, "-fsyntax-only", "-x", language, "-"]
                input_text = source["text"]
            else:
                command = [executable, "-fsyntax-only", str(source["path"])]
                input_text = None
            try:
                result = subprocess.run(command, cwd=self.workspace, shell=False,
                                        input=input_text, capture_output=True, text=True,
                                        timeout=self.timeout)
                output = (result.stdout + result.stderr)[:self.output_limit]
                outputs.append({"file": filename, "ok": result.returncode == 0,
                                "output": output, "returncode": result.returncode})
            except (OSError, subprocess.TimeoutExpired) as exc:
                outputs.append({"file": filename, "ok": False, "output": str(exc)})
        return {"ok": all(item["ok"] for item in outputs), "files_checked": len(outputs),
                "results": outputs,
                "text": "\n".join(f"{item['file']}: {'passed' if item['ok'] else 'failed'}\n{item['output']}"
                                  for item in outputs)}

    def _patch_test_verify(self, patch_text):
        changes = _apply_unified_patch(self.workspace, patch_text)
        if not changes:
            raise ValueError("Patch contains no supported file changes.")
        try:
            compile_result = self._analyze_python(
                [path for path in changes if path.suffix.lower() == ".py"], "python_compile")
            tests = self._run_tests()
            ok = compile_result["ok"] and tests["ok"]
            if not ok:
                raise _VerificationFailed(compile_result, tests)
            return {"ok": True, "changed_files": [p.relative_to(self.workspace).as_posix()
                                                   for p in changes],
                    "compile": compile_result, "tests": tests,
                    "text": "Patch applied; Python compilation and available tests passed."}
        except _VerificationFailed as failure:
            for path, original in changes.items():
                path.write_bytes(original)
            return {"ok": False, "rolled_back": True,
                    "compile": failure.compile_result, "tests": failure.test_result,
                    "text": "Patch verification failed. Changed source files were restored."}
        except Exception:
            for path, original in changes.items():
                path.write_bytes(original)
            raise


class _VerificationFailed(Exception):
    def __init__(self, compile_result, test_result):
        self.compile_result = compile_result
        self.test_result = test_result


def _apply_unified_patch(workspace, patch_text):
    lines = patch_text.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)
    changes = {}
    staged = {}
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        old_name = lines[i][4:].split("\t", 1)[0].strip().removeprefix("a/")
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError("Malformed unified diff: expected a +++ file header.")
        new_name = lines[i][4:].split("\t", 1)[0].strip().removeprefix("b/")
        i += 1
        if old_name == "/dev/null" or new_name == "/dev/null" or old_name != new_name:
            raise ValueError("Only in-place edits to existing workspace files are supported.")
        relative = PurePosixPath(old_name.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Patch paths must remain inside the configured workspace.")
        path = (workspace / Path(*relative.parts)).resolve()
        if workspace not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Patch target is not an existing regular workspace file: {old_name}")
        original_bytes = path.read_bytes()
        newline = "\r\n" if b"\r\n" in original_bytes else "\n"
        source = original_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        source_lines = source.splitlines(keepends=True)
        offset = 0
        saw_hunk = False
        while i < len(lines) and not lines[i].startswith(("--- ", "diff --git ")):
            header = lines[i]
            if not header.startswith("@@ "):
                i += 1
                continue
            saw_hunk = True
            hunk_match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
            if not hunk_match:
                raise ValueError("Malformed unified diff hunk header.")
            expected = max(0, int(hunk_match.group(1)) - 1 + offset)
            i += 1
            before, after = [], []
            while i < len(lines) and lines[i][:1] in (" ", "+", "-", "\\"):
                line = lines[i]
                if line.startswith("\\"):
                    i += 1
                    continue
                if line[0] in (" ", "-"):
                    before.append(line[1:])
                if line[0] in (" ", "+"):
                    after.append(line[1:])
                i += 1
            if source_lines[expected:expected + len(before)] != before:
                raise ValueError(f"Patch context did not match {old_name}; no files were changed.")
            source_lines[expected:expected + len(before)] = after
            offset += len(after) - len(before)
        if not saw_hunk:
            raise ValueError(f"No valid hunks found for {old_name}.")
        changes[path] = original_bytes
        source_newline = "".join(source_lines).replace("\n", newline)
        staged[path] = source_newline.encode("utf-8")
    written = []
    try:
        for path, contents in staged.items():
            path.write_bytes(contents)
            written.append(path)
    except Exception:
        for path in written:
            path.write_bytes(changes[path])
        raise
    return changes

