# Prism Self-Independent Vision

## 1. The real goal

Prism is not intended to be just a wrapper around Claude, GPT, Gemini or NVIDIA.

The long-term goal is:

> Move as much work as technically possible from an external AI API into Prism's
> own deterministic software, local computation, local models and autonomous
> execution engine.

Cloud AI providers should become optional accelerators, not mandatory dependencies.

The system should continue to perform useful work when every cloud API key is absent.

## 2. What "self-independent" means

Self-independent does NOT mean that Python code can magically reproduce the learned
knowledge and reasoning of a frontier foundation model.

There are two fundamentally different categories of work.

### A. Work that should be moved into Prism itself

These should normally be deterministic software:

- arithmetic
- statistics
- CSV/Excel processing
- SQL
- database operations
- file operations
- PDF extraction
- OCR
- document conversion
- image resizing/conversion
- audio/video processing
- FFmpeg
- code compilation
- test execution
- linting
- formatting
- Git operations
- project indexing
- code search
- dependency inspection
- HTTP/API calls
- web retrieval
- caching
- source extraction
- deduplication
- ranking
- data validation
- schema validation
- scheduling
- job management
- retries
- monitoring
- logging
- result verification
- deterministic workflow execution

### B. Work that fundamentally benefits from a learned model

Examples:

- understanding ambiguous natural language
- open-ended reasoning
- difficult code design
- interpreting an image semantically
- generating natural language
- deciding among unfamiliar approaches
- complex planning when no deterministic rule exists

Prism should minimize this category, use local models first when possible, and
use cloud models only when the configured policy permits them.

## 3. Core principle

The architecture follows:

    deterministic software > specialized local computation > local model > cloud model

for each task where the preceding layer can reliably solve it.

The system should never call an expensive model merely because a tool can already
solve the problem exactly.

## 4. The desired operating modes

### Offline mode

No cloud API is required.

    User
      |
      v
    Prism
      |
      +-- deterministic engine
      +-- local tools
      +-- local databases
      +-- local files
      +-- local model (optional)
      |
      +-- result

### Hybrid mode

Prism can use cloud models for tasks that exceed local capabilities.

    Prism
      |
      +-- local deterministic execution
      +-- local model
      +-- optional Claude/GPT/Gemini/NVIDIA

### Cloud-assisted mode

A cloud model can be used as a specialist, but Prism remains the execution
environment and owns state, tools, verification and permissions.

## 5. Success criterion

A request should not be measured by "which model answered it."

It should be measured by:

- Was the task completed?
- How much deterministic work was performed without an LLM?
- How many model calls were required?
- Could the task run offline?
- Was the result independently verified?
- Was the source/data correct?
- Was the generated artifact actually created and tested?

## 6. Long-term target

The ideal flow is:

    understand
       |
       v
    classify
       |
       +---- deterministic ---> execute directly
       |
       +---- structured API ---> retrieve directly
       |
       +---- computation -----> Python/C++/CUDA/etc.
       |
       +---- retrieval --------> web/search/index
       |
       +---- local model ------> use local model
       |
       +---- hard reasoning --> optional cloud model
       |
       v
    verify
       |
       v
    return result

The cloud model should be the last resort for work that genuinely requires
general learned reasoning, not the default engine for every operation.
