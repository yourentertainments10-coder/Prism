/* ============ Prism AI — frontend ============ */
"use strict";

const $ = (id) => document.getElementById(id);
const chatScroll = $("chatScroll"), chatInner = $("chatInner"), welcome = $("welcome");
const input = $("input"), sendBtn = $("sendBtn"), stopBtn = $("stopBtn");
const chatListEl = $("chatList"), modelSelect = $("modelSelect");
const sidebar = $("sidebar"), scrim = $("scrim");
const attachmentsEl = $("attachments"), fileInput = $("fileInput");
const webToggle = $("webToggle"), agentToggle = $("agentToggle");

let chats = JSON.parse(localStorage.getItem("nova_chats") || "[]");
let currentId = null;
let abortCtrl = null;
let pendingFiles = [];   // {name, text} or {name, dataUrl, isImage}
let webOn = false;
let agentOn = false;

const hasLibs = typeof marked !== "undefined" && typeof DOMPurify !== "undefined";
if (typeof mermaid !== "undefined") mermaid.initialize({ startOnLoad: false, theme: "neutral" });
if (hasLibs) marked.setOptions({ breaks: true, gfm: true });

/* ---------- persistence ---------- */
function save() { localStorage.setItem("nova_chats", JSON.stringify(chats)); }
function currentChat() { return chats.find((c) => c.id === currentId); }
function newChat() {
  const c = { id: Date.now().toString(36), title: "New chat", messages: [] };
  chats.unshift(c); currentId = c.id; save();
  renderChatList(); renderMessages();
  closeSidebarMobile();
  input.focus();
}
function deleteChat(id, ev) {
  ev.stopPropagation();
  chats = chats.filter((c) => c.id !== id);
  if (currentId === id) currentId = chats[0]?.id || null;
  if (!currentId) { save(); newChat(); return; }
  save(); renderChatList(); renderMessages();
}

/* ---------- rendering ---------- */
function renderChatList() {
  chatListEl.innerHTML = "";
  for (const c of chats) {
    const el = document.createElement("div");
    el.className = "chat-item" + (c.id === currentId ? " active" : "");
    el.innerHTML = `<span class="title"></span><button class="del" title="Delete">🗑</button>`;
    el.querySelector(".title").textContent = c.title;
    el.onclick = () => { currentId = c.id; renderChatList(); renderMessages(); closeSidebarMobile(); };
    el.querySelector(".del").onclick = (ev) => deleteChat(c.id, ev);
    chatListEl.appendChild(el);
  }
  const c = currentChat();
  $("topbarTitle").textContent = c ? c.title : "New chat";
}

function mdToHtml(text) {
  if (!hasLibs) { const d = document.createElement("div"); d.textContent = text; return d.innerHTML; }
  return DOMPurify.sanitize(marked.parse(text), { ADD_TAGS: ["svg", "path", "circle", "rect", "line", "polyline", "polygon", "g", "text", "ellipse", "defs", "marker", "tspan"], ADD_ATTR: ["viewBox", "xmlns", "fill", "stroke", "stroke-width", "d", "cx", "cy", "r", "x", "y", "x1", "x2", "y1", "y2", "points", "width", "height", "transform", "font-size", "text-anchor", "rx", "ry", "marker-end", "stroke-dasharray", "opacity", "font-weight"] });
}

function enhanceContent(el) {
  // wrap code blocks with header + copy button; render mermaid & svg
  el.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    if (pre.parentElement.classList.contains("code-block")) return;
    const langMatch = (code.className || "").match(/language-([\w-]+)/);
    const lang = langMatch ? langMatch[1] : "";

    if (lang === "mermaid" && typeof mermaid !== "undefined") {
      const box = document.createElement("div");
      box.className = "mermaid-box";
      const graph = document.createElement("pre");
      graph.className = "mermaid";
      graph.textContent = code.textContent;
      box.appendChild(graph);
      pre.replaceWith(box);
      mermaid.run({ nodes: [graph] }).catch(() => { box.replaceWith(pre); });
      return;
    }
    if (lang === "svg" && code.textContent.trim().startsWith("<svg")) {
      const box = document.createElement("div");
      box.className = "svg-box";
      box.innerHTML = DOMPurify ? DOMPurify.sanitize(code.textContent, { USE_PROFILES: { svg: true, svgFilters: true } }) : "";
      if (box.querySelector("svg")) { pre.replaceWith(box); return; }
    }

    const wrap = document.createElement("div");
    wrap.className = "code-block";
    const head = document.createElement("div");
    head.className = "code-head";
    head.innerHTML = `<span></span><span class="code-btns"></span>`;
    head.querySelector("span").textContent = lang || "code";
    const btns = head.querySelector(".code-btns");

    if (lang === "python" || lang === "py") {
      const run = document.createElement("button");
      run.className = "copy-btn";
      run.textContent = "▶ Run";
      run.onclick = async () => {
        run.textContent = "Running…"; run.disabled = true;
        let outEl = wrap.querySelector(".run-output");
        if (!outEl) { outEl = document.createElement("pre"); outEl.className = "run-output"; wrap.appendChild(outEl); }
        try {
          const r = await fetch("/api/run_code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: code.textContent }) });
          outEl.textContent = (await r.json()).output;
        } catch (e) { outEl.textContent = "Run failed: " + e.message; }
        run.textContent = "▶ Run"; run.disabled = false;
      };
      btns.appendChild(run);
    }
    if (lang === "html") {
      const prev = document.createElement("button");
      prev.className = "copy-btn";
      prev.textContent = "🖼 Preview";
      prev.onclick = () => showArtifact(code.textContent);
      btns.appendChild(prev);
    }
    const copy = document.createElement("button");
    copy.className = "copy-btn";
    copy.textContent = "Copy";
    copy.onclick = (ev) => {
      navigator.clipboard.writeText(code.textContent).then(() => {
        ev.target.textContent = "Copied ✓";
        setTimeout(() => (ev.target.textContent = "Copy"), 1500);
      });
    };
    btns.appendChild(copy);
    pre.replaceWith(wrap);
    wrap.appendChild(head);
    wrap.appendChild(pre);
    if (typeof hljs !== "undefined" && lang && lang !== "mermaid") {
      try { hljs.highlightElement(code); } catch (e) {}
    }
  });
}

/* ---------- artifact preview ---------- */
let artifactHtml = "";
function showArtifact(html) {
  artifactHtml = html;
  $("artifactPanel").classList.remove("hidden");
  document.querySelector(".app").classList.add("artifact-open");
  $("artifactFrame").srcdoc = html;
}
$("artifactClose").onclick = () => {
  $("artifactPanel").classList.add("hidden");
  document.querySelector(".app").classList.remove("artifact-open");
};
$("artifactOpen").onclick = () => {
  const blob = new Blob([artifactHtml], { type: "text/html" });
  window.open(URL.createObjectURL(blob), "_blank");
};

function extractThinking(raw) {
  // pull <think>...</think> out of the text (some reasoning models emit it)
  let thinking = "";
  let text = raw.replace(/<think>([\s\S]*?)(<\/think>|$)/g, (m, t) => { thinking += t; return ""; });
  return { thinking: thinking.trim(), text: text };
}

function messageEl(role) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = `
    <div class="avatar">${role === "user" ? "🧑" : "✨"}</div>
    <div class="msg-body">
      <div class="who">${role === "user" ? "You" : "Prism"}</div>
      <div class="content"></div>
    </div>`;
  return div;
}

function renderMessages() {
  chatInner.querySelectorAll(".msg").forEach((m) => m.remove());
  const c = currentChat();
  const empty = !c || c.messages.length === 0;
  welcome.classList.toggle("hidden", !empty);
  if (!c) return;
  for (const m of c.messages) {
    const el = messageEl(m.role);
    const content = el.querySelector(".content");
    if (m.role === "user") {
      if (m.files?.length) {
        for (const f of m.files) {
          const tag = document.createElement("div");
          tag.className = "file-tag";
          tag.textContent = "📎 " + f;
          el.querySelector(".msg-body").insertBefore(tag, content);
        }
      }
      content.textContent = m.display ?? (typeof m.content === "string" ? m.content : "[image]");
    } else {
      const { thinking, text } = extractThinking(m.content || "");
      if (m.actions?.length) renderActionsBlock(el.querySelector(".msg-body"), m.actions, content);
      if (thinking || m.reasoning) {
        const d = document.createElement("details");
        d.className = "thinking";
        d.innerHTML = `<summary>💭 Thinking</summary><div class="think-body"></div>`;
        d.querySelector(".think-body").textContent = (m.reasoning || "") + thinking;
        el.querySelector(".msg-body").insertBefore(d, content);
      }
      content.innerHTML = mdToHtml(text);
      enhanceContent(content);
      addActions(el, m);
    }
    chatInner.appendChild(el);
  }
  renderChatList();
  scrollBottom(true);
}

function addActions(el, m) {
  const bar = document.createElement("div");
  bar.className = "msg-actions";
  const copy = document.createElement("button");
  copy.textContent = "Copy";
  copy.onclick = () => navigator.clipboard.writeText(m.content).then(() => {
    copy.textContent = "Copied ✓"; setTimeout(() => (copy.textContent = "Copy"), 1500);
  });
  const regen = document.createElement("button");
  regen.textContent = "↻ Regenerate";
  regen.onclick = () => regenerate();
  bar.append(copy, regen);
  el.querySelector(".msg-body").appendChild(bar);
}

function scrollBottom(force) {
  const nearBottom = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 140;
  if (force || nearBottom) chatScroll.scrollTop = chatScroll.scrollHeight;
}

/* ---------- sending ---------- */
async function send(textOverride) {
  const text = (textOverride ?? input.value).trim();
  if (!text && pendingFiles.length === 0) return;
  if (abortCtrl) return;
  if (!currentChat()) newChat();
  const chat = currentChat();

  // Build the user message
  const fileNames = pendingFiles.map((f) => f.name);
  let apiContent, display = text;
  const images = pendingFiles.filter((f) => f.isImage);
  const docs = pendingFiles.filter((f) => !f.isImage);
  let fullText = text;
  for (const d of docs) {
    fullText += `\n\n[Attached file: ${d.name}]\n\`\`\`\n${d.text}\n\`\`\``;
  }
  if (images.length) {
    apiContent = [{ type: "text", text: fullText || "Describe this image." }];
    for (const im of images) apiContent.push({ type: "image_url", image_url: { url: im.dataUrl } });
  } else {
    apiContent = fullText;
  }

  chat.messages.push({ role: "user", content: apiContent, display: display || "(file attached)", files: fileNames });
  if (chat.title === "New chat" && text) {
    chat.title = text.slice(0, 42) + (text.length > 42 ? "…" : "");
  }
  pendingFiles = []; renderAttachments();
  input.value = ""; autoGrow();
  save(); renderMessages();

  await streamAssistant();
}

let liveBubble = null;
function setThinkingBubble(label) {
  if (!liveBubble) {
    liveBubble = messageEl("assistant");
    chatInner.appendChild(liveBubble);
  }
  liveBubble.querySelector(".content").innerHTML =
    `<span style="color:var(--muted);font-size:13px">${label} </span><span class="typing"><span></span><span></span><span></span></span>`;
  scrollBottom(true);
}

async function streamAssistant() {
  const chat = currentChat();
  setThinkingBubble("");
  sendBtn.classList.add("hidden"); stopBtn.classList.remove("hidden");
  abortCtrl = new AbortController();

  // strip local-only fields before sending
  const apiMessages = chat.messages.map(({ role, content }) => ({ role, content }));

  let full = "", reasoning = "", errored = false;
  const actions = [];   // tool steps: {name, label, done}
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: apiMessages, model: modelSelect.value, web: webOn, agent: agentOn }),
      signal: abortCtrl.signal,
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        let j;
        try { j = JSON.parse(part.slice(6)); } catch (e) { continue; }
        if (j.error) {
          errored = true;
          liveBubble.querySelector(".content").innerHTML = `<div class="err"></div>`;
          liveBubble.querySelector(".err").textContent = j.error;
          break;
        }
        if (j.notice) { actions.push({ name: "notice", label: j.notice, done: true }); renderLive(full, reasoning, actions); }
        if (j.tool) { actions.push({ name: j.tool, label: j.label || "", done: false }); renderLive(full, reasoning, actions); }
        if (j.tool_done) { const a = actions.findLast((x) => x.name === j.tool_done && !x.done); if (a) a.done = true; renderLive(full, reasoning, actions); }
        if (j.reasoning) reasoning += j.reasoning;
        if (j.content) full += j.content;
        if (j.content || j.reasoning) renderLive(full, reasoning, actions);
      }
      if (errored) break;
    }
  } catch (e) {
    if (e.name !== "AbortError") {
      errored = true;
      if (liveBubble) {
        liveBubble.querySelector(".content").innerHTML = `<div class="err"></div>`;
        liveBubble.querySelector(".err").textContent = "Connection error: " + e.message;
      }
    }
  }

  abortCtrl = null;
  sendBtn.classList.remove("hidden"); stopBtn.classList.add("hidden");

  if (!errored && (full || reasoning)) {
    chat.messages.push({ role: "assistant", content: full, reasoning: reasoning || undefined,
                         actions: actions.length ? actions : undefined });
    save();
    liveBubble = null;
    renderMessages();
  } else if (errored) {
    // keep the error bubble visible; it clears on the next render
    liveBubble = null;
  } else {
    // aborted before any content arrived — remove the empty bubble
    liveBubble?.remove();
    liveBubble = null;
  }
}

const TOOL_ICONS = { web_search: "🔎", fetch_url: "🌐", generate_image: "🎨", remember: "🧠",
                     run_python: "🐍", run_command: "💻", read_file: "📖", write_file: "📝",
                     list_files: "📁", notice: "ℹ️" };
function actionsHtml(actions) {
  return actions.map((a) =>
    `<div class="action ${a.done ? "done" : "busy"}"><span>${TOOL_ICONS[a.name] || "🔧"} ${a.name === "notice" ? "" : a.name}</span><em></em></div>`
  ).join("");
}
function fillActions(box, actions) {
  box.innerHTML = actionsHtml(actions);
  box.querySelectorAll(".action em").forEach((em, i) => { em.textContent = actions[i]?.label || ""; });
}
function renderActionsBlock(body, actions, before) {
  let box = body.querySelector(".actions");
  if (!box) {
    box = document.createElement("div");
    box.className = "actions";
    body.insertBefore(box, before);
  }
  fillActions(box, actions);
}

function renderLive(full, reasoning, actions) {
  if (!liveBubble) return;
  const body = liveBubble.querySelector(".msg-body");
  if (actions && actions.length) renderActionsBlock(body, actions, body.querySelector(".content"));
  const { thinking, text } = extractThinking(full);
  const allThinking = (reasoning || "") + thinking;
  let details = body.querySelector("details.thinking");
  if (allThinking && !details) {
    details = document.createElement("details");
    details.className = "thinking";
    details.open = !text;
    details.innerHTML = `<summary>💭 Thinking</summary><div class="think-body"></div>`;
    body.insertBefore(details, body.querySelector(".content"));
  }
  if (details) {
    details.querySelector(".think-body").textContent = allThinking;
    if (text) details.open = false;
  }
  const content = liveBubble.querySelector(".content");
  content.innerHTML = mdToHtml(text) + `<span class="typing"><span></span><span></span><span></span></span>`;
  enhanceContent(content);
  scrollBottom(false);
}

function regenerate() {
  const chat = currentChat();
  if (!chat || abortCtrl) return;
  // drop trailing assistant message(s), keep last user message
  while (chat.messages.length && chat.messages[chat.messages.length - 1].role === "assistant") {
    chat.messages.pop();
  }
  if (!chat.messages.length) return;
  save(); renderMessages();
  streamAssistant(null);
}

/* ---------- attachments ---------- */
function renderAttachments() {
  attachmentsEl.innerHTML = "";
  pendingFiles.forEach((f, i) => {
    const el = document.createElement("div");
    el.className = "attachment";
    el.innerHTML = f.isImage
      ? `<img alt=""><span></span><button class="rm">✕</button>`
      : `📄 <span></span><button class="rm">✕</button>`;
    if (f.isImage) el.querySelector("img").src = f.dataUrl;
    el.querySelector("span").textContent = f.name;
    el.querySelector(".rm").onclick = () => { pendingFiles.splice(i, 1); renderAttachments(); };
    attachmentsEl.appendChild(el);
  });
}

fileInput.onchange = async () => {
  for (const file of fileInput.files) {
    if (file.type.startsWith("image/")) {
      const dataUrl = await new Promise((res) => {
        const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(file);
      });
      pendingFiles.push({ name: file.name, dataUrl, isImage: true });
    } else {
      const fd = new FormData();
      fd.append("file", file);
      try {
        const r = await fetch("/api/upload", { method: "POST", body: fd });
        const j = await r.json();
        if (j.error) { alert(j.error); continue; }
        pendingFiles.push({ name: j.name + (j.truncated ? " (truncated)" : ""), text: j.text });
      } catch (e) { alert("Upload failed: " + e.message); }
    }
  }
  fileInput.value = "";
  renderAttachments();
};

/* ---------- UI wiring ---------- */
$("attachBtn").onclick = () => fileInput.click();
sendBtn.onclick = () => send();
stopBtn.onclick = () => abortCtrl?.abort();
$("newChatBtn").onclick = () => newChat();
webToggle.onclick = () => { webOn = !webOn; webToggle.classList.toggle("on", webOn); };
agentToggle.onclick = () => { agentOn = !agentOn; agentToggle.classList.toggle("on", agentOn); };

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 180) + "px";
}
input.addEventListener("input", autoGrow);

document.querySelectorAll(".chip").forEach((c) => {
  c.onclick = () => { input.value = c.dataset.q; input.focus(); autoGrow(); };
});

/* sidebar (mobile) */
$("openSidebar").onclick = () => { sidebar.classList.add("open"); scrim.classList.add("show"); };
$("closeSidebar").onclick = closeSidebarMobile;
scrim.onclick = closeSidebarMobile;
function closeSidebarMobile() { sidebar.classList.remove("open"); scrim.classList.remove("show"); }

modelSelect.onchange = () => {
  localStorage.setItem("nova_model", modelSelect.value);
  $("topbarModel").textContent = modelSelect.selectedOptions[0]?.textContent || "";
};

/* ---------- init ---------- */
async function init() {
  try {
    const r = await fetch("/api/config");
    const cfg = await r.json();
    modelSelect.innerHTML = "";
    for (const m of cfg.models) {
      const o = document.createElement("option");
      o.value = m.id;
      o.textContent = `${m.name} · ${m.tag}`;
      modelSelect.appendChild(o);
    }
    const savedModel = localStorage.getItem("nova_model");
    if (savedModel && cfg.models.some((m) => m.id === savedModel)) modelSelect.value = savedModel;
    $("topbarModel").textContent = modelSelect.selectedOptions[0]?.textContent || "";
    if (!cfg.hasKey || !cfg.keyLooksNvidia) $("keyBanner").classList.remove("hidden");
  } catch (e) {}

  if (chats.length) { currentId = chats[0].id; renderChatList(); renderMessages(); }
  else newChat();
}
init();
