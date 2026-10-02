# Architecture

Prism has five core layers.

1. Model layer: Claude, GPT, Gemini, NVIDIA, Ollama.
2. Router: chooses a provider/model.
3. Tool runtime: controlled file, Python, terminal, Git, web and DB operations.
4. Planner/verifier: plan work and independently check results.
5. Memory: persistent task/conversation context.

The model is the reasoning engine. Prism is the execution environment.

A mature coding workflow is:

UNDERSTAND -> INSPECT -> PLAN -> IMPLEMENT -> TEST -> FIX -> VERIFY -> REPORT

A mature research workflow is:

UNDERSTAND -> determine whether current data is needed -> official API/structured source
-> reputable source/search -> extract -> cross-check -> cite -> report
