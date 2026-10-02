# AI Usage Minimization Strategy

## Objective

Minimize model/API usage without reducing correctness.

## Principle

Do not use an LLM to perform work that normal software can perform more reliably,
cheaply and deterministically.

## Level 0: No AI

Examples:

- add numbers
- sort data
- convert units
- parse JSON
- validate schema
- rename files
- copy files
- hash files
- calculate statistics
- execute SQL
- compile code
- run tests
- convert video with FFmpeg

## Level 1: Local algorithms

Use:

- regex
- parsers
- AST
- static analysis
- search indexes
- rule engines
- classifiers
- heuristics
- caching

## Level 2: Local specialized models

Use Ollama/local models only when semantic understanding is needed.

## Level 3: Cloud AI

Use Claude/GPT/Gemini/NVIDIA only when the local stack cannot reasonably solve
the task or when the user explicitly requests a particular model.

## Important optimization

Do not call a model separately for every tool operation.

Prefer:

```text
one planning/reasoning step
        |
        +--> many deterministic tool operations
        |
        +--> one verification step
```

instead of:

```text
model -> tool
model -> tool
model -> tool
model -> tool
...
```

## Cache aggressively

Cache:

- web responses
- parsed documents
- project indexes
- dependency metadata
- model outputs where safe
- computed datasets
- source retrieval
- embeddings
- build results

## Learn from repeated workflows

When a task becomes predictable, convert it from an AI workflow into a deterministic
workflow.

Example:

First time:

```text
LLM -> understand -> execute
```

After enough repetition:

```text
workflow template -> execute directly
```

This is one of the strongest ways Prism can become increasingly independent.

## Self-improvement boundary

Prism may generate proposed new tools/workflows, but they must be reviewed,
tested and registered before becoming trusted capabilities.

Never let the agent silently rewrite its own security boundary.
