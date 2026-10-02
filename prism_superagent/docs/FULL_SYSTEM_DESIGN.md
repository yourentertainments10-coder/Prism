# Prism Full System Design

## 1. System objective

Build Prism as a local-first autonomous computer, coding, research, data and
automation system.

It should be capable of:

- understanding user requests
- deciding whether AI is actually required
- executing deterministic work itself
- using specialized tools and APIs
- using local models when useful
- optionally consulting cloud AI
- inspecting its own workspace
- writing and modifying code
- executing code
- running tests
- diagnosing failures
- retrying
- verifying results
- maintaining task state
- remembering project context
- producing artifacts

## 2. Architecture

```text
                         USER
                           |
                           v
                    PRISM INTERFACE
                  / CLI / Web / API
                           |
                           v
                  REQUEST CLASSIFIER
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
    DETERMINISTIC      SPECIALIZED       REASONING
       ENGINE            ENGINES           ENGINE
          |                |                |
          |                |         +------+------+
          |                |         |             |
          |                |      LOCAL MODEL   CLOUD MODEL
          |                |         |             |
          +----------------+---------+-------------+
                           |
                           v
                    EXECUTION ENGINE
                           |
       +---------+---------+---------+----------+
       |         |         |         |          |
      Code      Data      Web      Files      Media
       |         |         |         |          |
     Python     SQL      HTTP      Git      FFmpeg/OCR
     C/C++    Pandas    APIs     Build       PDF/audio
     Rust     NumPy     Search   Tests       image/video
                           |
                           v
                     VERIFICATION
                           |
                +----------+----------+
                |                     |
             PASS                  FAIL
                |                     |
                v                     v
              RESULT             DIAGNOSE/FIX
                                      |
                                      +----> EXECUTE
```

## 3. Components

### 3.1 Request classifier

Classifies work before invoking a model.

Examples:

- "2+2" -> arithmetic engine
- "average these 500,000 rows" -> Pandas
- "what is in this PDF?" -> PDF parser/OCR
- "how many rows are in table X?" -> SQL
- "what is India's current ranking?" -> current-data retrieval
- "fix this Python error" -> coding agent
- "design an unfamiliar distributed system" -> reasoning engine

This classifier can initially be rule based.

Later it can use a small local model only when rules are ambiguous.

### 3.2 Deterministic engine

This is the heart of self-independence.

It contains specialized executors.

```text
engine/
  arithmetic
  statistics
  dataframe
  sql
  files
  documents
  pdf
  ocr
  image
  audio
  video
  http
  web
  search
  git
  compiler
  test
  package
  scheduler
  validation
```

### 3.3 Tool registry

Every capability has:

- name
- description
- input schema
- output schema
- permissions
- timeout
- resource limit
- verification method

This makes tools composable and inspectable.

### 3.4 Planner

Plans multi-step tasks.

It should not execute arbitrary actions directly.

The planner creates an explicit task graph.

Example:

```text
Task: Analyze an Excel file

1. discover workbook
2. inspect sheets
3. infer schema
4. validate data
5. calculate requested metrics
6. generate charts
7. verify calculations
8. create report
9. return files + findings
```

### 3.5 Executor

Executes the task graph.

It handles:

- dependencies
- retries
- timeouts
- cancellation
- state
- outputs
- failures

### 3.6 Verifier

Verification is a first-class component, not a final sentence from an LLM.

Examples:

- tests exit code 0
- compiler succeeded
- generated PDF exists
- JSON validates against schema
- SQL result is structurally valid
- numeric calculations pass independent checks
- HTTP response has expected status
- output video can be decoded
- Git diff matches intended files

### 3.7 Memory

Separate memory into:

```text
User memory
Project memory
Task state
Tool history
Artifact metadata
Source cache
Model conversation
```

Do not put everything into one giant prompt.

## 4. Task state machine

```text
RECEIVED
   |
CLASSIFIED
   |
PLANNED
   |
EXECUTING
   |
+--+----------------+
|                   |
SUCCESS            FAILURE
|                   |
v                   v
VERIFY          DIAGNOSE
|                   |
+--------<----------+
|
VERIFIED
|
COMPLETED
```

Add a hard retry limit to prevent loops.

## 5. Artifact system

Every significant operation should create structured artifacts:

```text
Artifact
- id
- task_id
- type
- path
- source
- created_at
- checksum
- validation_status
```

Examples:

- report.pdf
- analysis.xlsx
- chart.png
- compiled.exe
- test-results.json
- research.json
- source-cache.json

## 6. Capability graph

Instead of hard-coding one route per request, Prism can maintain capabilities:

```text
calculate
  -> arithmetic
  -> python
  -> pandas

research_current_fact
  -> web_search
  -> official_api
  -> source_parser

edit_code
  -> code_search
  -> filesystem
  -> patch
  -> terminal
  -> tests
```

The planner chooses a path through this graph.

## 7. Model layer

Models are plugins.

```text
models/
  anthropic
  openai
  google
  nvidia
  ollama
```

The rest of Prism must not depend directly on one provider.

## 8. Model policy

Default:

```text
Try deterministic solution.
If unavailable:
    try specialized non-LLM tool.
If ambiguity remains:
    try local model.
If task exceeds local capability and policy permits:
    try cloud model.
Verify result.
```

## 9. Research source hierarchy

For current information:

```text
official API
   >
official structured data
   >
official webpage
   >
reputable secondary source
   >
search result
   >
manual upload
```

The system should record the source and retrieval time.

## 10. Coding agent

The coding subsystem should support:

```text
discover project
    -> index code
    -> search symbols
    -> inspect files
    -> create plan
    -> edit/patch
    -> format
    -> build
    -> test
    -> inspect errors
    -> repair
    -> retest
    -> review diff
```

It should never report success merely because a file was written.

## 11. Data agent

Support:

- CSV
- Excel
- JSON
- Parquet
- SQL
- Pandas
- NumPy
- statistics
- visualization

The model should orchestrate; Python should calculate.

## 12. Media agent

Use deterministic libraries first:

- FFmpeg
- Pillow
- OpenCV
- librosa
- image/video metadata

Use AI only for semantic tasks that require it.

## 13. Browser agent

Browser automation should be isolated.

Capabilities:

- navigate
- inspect
- click
- type
- download
- screenshot

Dangerous actions need confirmation.

## 14. Security boundary

Prism is effectively a computer-control system once terminal/browser tools exist.

Therefore:

- sandbox
- workspace isolation
- allowlists
- approval gates
- resource limits
- network policy
- secret protection
- audit logs

are architectural requirements, not optional polish.

## 15. Observability

Track every task:

```text
task_id
request
classification
plan
tool calls
model calls
latency
cost
outputs
errors
retries
verification
final status
```

This lets us answer the most important optimization question:

> How much work did Prism perform without AI?
