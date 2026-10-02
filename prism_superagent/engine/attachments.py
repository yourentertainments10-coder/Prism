"""Attachment extraction helpers shared by deterministic task classifiers."""

import re

_FENCED_ATTACHMENT = re.compile(
    r"\[Attached file: ([^\]]+)\]\s*```[^\n]*\n([\s\S]*?)```", re.IGNORECASE
)


def attached_documents(content):
    if not isinstance(content, str):
        return []
    return [{"filename": name, "text": body.strip()}
            for name, body in _FENCED_ATTACHMENT.findall(content)]


def request_text(content):
    """Remove pasted attachment bodies so their contents aren't intent cues."""
    if not isinstance(content, str):
        return ""
    return _FENCED_ATTACHMENT.sub(" ", content).strip()

