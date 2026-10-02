"""Explicit intent rules for read-only project tools and patch workflows."""

import re

from prism_superagent.engine.attachments import attached_documents, request_text


def classify_development_request(content):
    if not isinstance(content, str):
        return None
    request = request_text(content)
    lower = request.lower()
    patch_doc = next((doc for doc in attached_documents(content)
                      if doc["filename"].lower().endswith((".patch", ".diff"))), None)
    if patch_doc and re.search(r"\b(apply|apply this|apply the)\s+(?:the\s+)?patch\b", lower):
        return "patch_test_verify", {"patch": patch_doc["text"]}
    attached_source = next((doc for doc in attached_documents(content)
                            if doc["filename"].lower().endswith((".c", ".h", ".cpp", ".cc", ".cxx", ".hpp"))), None)
    if re.search(r"\b(compile|build|check syntax)\b", lower):
        if attached_source:
            return "compiler_check", {"sources": [attached_source]}
        target = re.search(r"([\w./\\-]+\.(?:c|h|cpp|cc|cxx|hpp))\b", request, re.I)
        if target:
            return "compiler_check", {"path": target.group(1)}
    if re.search(r"\b(git\s+status|status\s+of\s+(?:the\s+)?git|working tree status)\b", lower):
        return "git_status", {}
    if re.search(r"\b(git\s+diff|show\s+(?:the\s+)?diff|what changed in the working tree)\b", lower):
        return "git_diff", {}
    if re.search(r"\b(run|execute)\s+(?:the\s+)?tests?\b|\bpytest\b|\bunittest discover\b", lower):
        return "run_tests", {}
    if re.search(r"\b(lint|linting)\b", lower):
        return "python_lint", _target_path(request)
    if re.search(r"\b(ast|abstract syntax tree|list (?:the )?functions and classes)\b", lower):
        return "python_ast", _target_path(request)
    if re.search(r"\b(check|compile|validate)\b.*\b(python|syntax|\.py files?)\b", lower):
        return "python_compile", _target_path(request)
    if re.search(r"\b(inspect|inventory|list|summarize)\b.*\b(project|workspace|repository|repo)\b", lower):
        return "project_inspect", {}
    return None


def _target_path(request):
    match = re.search(r"\b(?:in|for|file)\s+[`\"]?([\w./\\-]+\.py)[`\"]?", request, re.IGNORECASE)
    return {"path": match.group(1)} if match else {}

