# Prism AI — NVIDIA + Claude powered agentic chatbot

A ChatGPT + Claude + coding-agent style app running on NVIDIA's free inference API, with optional real Claude models via the Anthropic API.

## Capabilities
- **Live web** — the model can search (DuckDuckGo) and read full web pages on its own, then cite sources. Toggle 🌐 to make it prefer web research.
- **Real image generation** — ask for an image; it appears right in the chat (NVIDIA image models, with a free fallback provider). Saved under `workspace/images/`.
- **Run code** — the model can execute Python in the persistent `workspace/` folder (like ChatGPT's Code Interpreter). You can also press **▶ Run** on any Python code block in a reply.
- **Memory across sessions** — tell it things about you; it saves facts to `memories.json` and recalls them in every future conversation.
- **Agent mode (🤖 toggle)** — Claude Code-style: it can list/read/write files and run shell commands inside `workspace/`, so it can build and test whole mini-projects autonomously. Everything is confined to that folder.
- **Artifacts** — HTML code blocks get a 🖼 **Preview** button that renders the page/app live beside the chat.
- **Files in** — attach code, .txt, .csv, .json, .pdf and ask questions; attach images (auto-routes to Llama 3.2 90B Vision).
- **Rich output** — Markdown, syntax-highlighted code with copy buttons, tables, Mermaid diagrams, SVG.
- Streaming, model picker (Kimi K3, DeepSeek V4, Nemotron, GPT-OSS, Mistral, Codestral, Claude Opus 5, Claude Sonnet 5…), auto-fallback when an NVIDIA model is rate-limited, collapsible "Thinking" for reasoning models, chat history, responsive on laptop/tablet/mobile.

## Setup
1. Put your NVIDIA key in `.env`:
   ```
   NVIDIA_API_KEY=nvapi-xxxxxxxxxxxx
   ```
   (Free at https://build.nvidia.com → any model → Get API Key.)
2. (Optional) Add an Anthropic key to unlock Claude Opus 5 / Claude Sonnet 5 in the model picker:
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
   ```
   (Get one at https://console.anthropic.com.) Without this key, the Claude
   models will show an authentication error if selected — every NVIDIA model
   still works fine on its own.
3. (Optional, recommended for deploying) Add a free Postgres database so
   long-term memory survives restarts/redeploys on hosts with an ephemeral
   filesystem (e.g. Render's free tier):
   ```
   DATABASE_URL=postgresql://postgres.xxxx:PASSWORD@aws-x-pooler.supabase.com:6543/postgres
   ```
   (Create a free project at https://supabase.com → Project Settings →
   Database → copy the "Connection pooling" URI.) Without this, memories are
   saved to `memories.json` on local disk, which is fine for local use but
   gets wiped on redeploy on ephemeral hosts.
4. Run:
   ```
   env\Scripts\python.exe app.py
   ```
5. Open http://127.0.0.1:5000

Note: `.env` is read only at startup — restart the server after changing it.

## Safety note on Agent mode
Agent mode lets the AI write files and run commands in the `workspace/` folder of
this project (30-second timeout per command). Keep it off unless you want that.

## Use on your phone (same Wi-Fi)
Change the last line of `app.py` to `app.run(host="0.0.0.0", port=5000)`, restart,
find your PC's IP with `ipconfig`, and open `http://<pc-ip>:5000` on the phone.
