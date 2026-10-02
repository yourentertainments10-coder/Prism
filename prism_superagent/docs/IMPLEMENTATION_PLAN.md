# Implementation Plan

The current starter should evolve in these phases.

## Phase 1 - Keep the foundation stable

Do not rewrite:

- provider abstraction
- existing timing instrumentation
- existing shared agent loop
- memory interface
- Flask API

First make tests pass.

## Phase 2 - Build the deterministic core

Create:

```text
engine/
  classifier.py
  dispatcher.py
  task_graph.py
  executor.py
  verifier.py
  cache.py
```

Add deterministic handlers for:

- arithmetic
- files
- JSON
- CSV/Excel
- SQL
- HTTP
- PDF
- Git
- tests
- build
- FFmpeg

## Phase 3 - Real structured tool calling

Every provider must support:

```text
assistant -> tool_call
Prism -> execute
Prism -> tool_result
assistant -> continue
```

Normalize provider-specific formats into one internal representation.

## Phase 4 - Coding autonomy

Add:

- project index
- symbol search
- patch editor
- test discovery
- compiler runner
- failure parser
- fix loop
- diff verifier

## Phase 5 - Research autonomy

Add:

- search provider interface
- official API adapters
- source extraction
- source ranking
- citation objects
- retrieval cache
- freshness checks

## Phase 6 - Data autonomy

Add:

- Pandas
- Excel
- CSV
- SQL
- charts
- report generation

## Phase 7 - Local intelligence

Add Ollama discovery:

```text
GET /api/tags
```

Select local models based on task capability.

## Phase 8 - Optional cloud escalation

Only after local/deterministic routes fail or the task policy explicitly asks
for cloud reasoning.

## Phase 9 - Browser/media/GPU

Add isolated tools for:

- Playwright
- OCR
- OpenCV
- FFmpeg
- CUDA
- C/C++
- Rust
- Docker

## Phase 10 - Production hardening

- authentication
- authorization
- sandbox
- task queue
- persistent state
- resource limits
- audit logs
- approvals
- observability
- backup/recovery
