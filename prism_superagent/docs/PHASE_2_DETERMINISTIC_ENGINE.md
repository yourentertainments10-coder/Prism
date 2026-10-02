# Phase 2: Universal Deterministic Engine

Prism now classifies clearly supported requests and runs them through the
existing local classifier -> task graph -> planner -> executor -> verifier ->
bounded cache pipeline. The Flask/SSE API, Anthropic and NVIDIA provider modules,
memory, timing instrumentation, frontend, and existing agent tools remain in
place. Requests that are ambiguous, unsupported, or require interpretation
continue through the selected existing provider.

## Phase 2A: math and structured data

- Arithmetic expressions, sums, means, descriptive statistics, percentiles,
  percentages, percent change, factorial, square root, GCD, and LCM.
- Unit conversions for length, mass, volume, time, and decimal/binary data
  units; Celsius/Fahrenheit conversions.
- Date differences and adding days, weeks, or months.
- CSV and Excel table statistics, monthly aggregations, sort/filter/deduplicate,
  row counts, CSV-to-JSON, and read-only SQL over attached tables or literals.
- JSON formatting and key/path lookup; XML formatting and tag lookup.

SQL runs in a temporary in-memory SQLite database with a read-only authorizer.
Attached files are ingested as data; SQL does not connect to external databases.

## Phase 2B: documents

- PDF text extraction, DOCX paragraph and table extraction, and Excel sheets.
- Local OCR for image attachments and scanned PDFs when the optional local OCR
  packages are installed. RapidOCR is the bundled Python backend; Tesseract is
  used when available. OCR is resource-limited by image size and page count.
- Text document comparison, CSV/XLSX table extraction, and heuristic table
  extraction from text-based PDFs.

PDF table detection is heuristic. Scanned or unusually formatted documents may
need a model or a dedicated external document tool for reliable interpretation.

## Phase 2C: development

- Workspace-confined Git status/diff and project inventory.
- Python AST summaries, syntax compilation, lightweight linting (or Ruff when
  installed), and explicitly requested Python test execution.
- C/C++ syntax checks when GCC, Clang, or MSVC is available.
- An attached unified diff can be applied to existing workspace files, then
  changed Python files are compiled and available tests are run. If verification
  fails, the modified source files are restored.

This patch workflow only supports in-place edits to existing files and Python
verification. It does not create/delete files, install packages, or apply a
patch outside the configured workspace.

## Phase 2D: web retrieval

- Explicit HTTPS URL retrieval and user-requested web search.
- Retrieval is limited to public hosts, refuses redirects, caps response bodies,
  records retrieval time and content SHA-256, and caches successful responses
  for a short time. Search uses DuckDuckGo HTML results.
- Multi-source checks report transport status and response fingerprints. These
  checks establish that a public URL returned a response; they do not establish
  that a source is authoritative or that its claims are true. Prism does not yet
  have specialized official API connectors or claim-level source verification.

## Routing and dependencies

The deterministic engine runs before Anthropic or NVIDIA. A known deterministic
operation is verified locally and returned without a model call. Unsupported
tasks continue through the user's selected provider; retrieval transport
failures can also fall through to that provider. A separate local-model routing
tier is not configured in this phase.

Base app dependencies remain in `requirements.txt`. Document support uses
`pypdf`, `python-docx`, and `openpyxl`. Local OCR uses Pillow, NumPy,
`rapidocr-onnxruntime`, and PyMuPDF. Ruff and pytest power the optional lint and
test tools. OCR and C/C++ compilation still depend on local runtime/compiler
availability.
