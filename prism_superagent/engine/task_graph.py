"""Small explicit task graph for deterministic Prism work."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskNode:
    node_id: str
    operation: str
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskGraph:
    task_id: str
    kind: str
    goal: str
    nodes: tuple[TaskNode, ...]

