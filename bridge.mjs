// Letta Agent SDK bridge. JSON lines on stdin, JSON lines on stdout.
// stdin:  {"cmd":"init"|"send"|"approve"|"tool_result"|"perm"|"abort"|"close", ...}
// stdout: {"ev":"text"|"think"|"tool"|"result"|"approval"|"done"|"error"|"queue", ...}
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { LettaAgentClient } from "@letta-ai/letta-agent-sdk";

const arg = (n, d) => {
  const i = process.argv.indexOf("--" + n);
  return i > -1 ? process.argv[i + 1] : d;
};

function wsUrl(raw) {
  const p = new URL(raw);
  p.protocol = (p.protocol === "https:" || p.protocol === "wss:") ? "wss:" : "ws:";
  if (!p.pathname || p.pathname === "/") p.pathname = "/ws";
  return p.toString();
}

const LETTA_URL = wsUrl(arg("url", "ws://127.0.0.1:4500"));
const AGENT = arg("agent", "");
const CONV = arg("conv", "");
const CWD = arg("cwd", process.cwd());
const PERM = arg("perm", "standard");
const MCP_FILE = arg("mcp-file", "");
const TOOLS_FILE = arg("tools-file", "");
const PERSONA_FILE = arg("persona-file", "");

const MCP = MCP_FILE ? JSON.parse(readFileSync(MCP_FILE, "utf8")) : {};
const TOOLS = TOOLS_FILE ? JSON.parse(readFileSync(TOOLS_FILE, "utf8")) : [];
const PERSONA = PERSONA_FILE ? readFileSync(PERSONA_FILE, "utf8").trim() : "You are MalO.";
const BASE = ["Read", "Write", "Edit", "Bash", "Grep", "Glob"];

const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const log = (m) => process.stderr.write("[bridge] " + m + "\n");

const approvals = new Map();
const inflight = new Map();
let seq = 0;
let session = null;
let perm = PERM;
const queue = [];
let running = false;

function pythonTool(spec) {
  return {
    name: spec.name,
    label: spec.label ?? spec.name,
    description: spec.description ?? "",
    parameters: spec.parameters ?? { type: "object", properties: {} },
    async execute(_id, input) {
      const id = "t" + ++seq;
      out({ ev: "tool", id, name: spec.name, input });
      const res = await new Promise((resolve, reject) => {
        inflight.set(id, resolve);
        setTimeout(() => {
          if (inflight.delete(id)) reject(new Error("python tool timed out"));
        }, 180_000);
      });
      return res.isError
        ? { isError: true, content: [{ type: "text", text: String(res.text ?? "error") }] }
        : { content: [{ type: "text", text: String(res.text ?? "") }] };
    },
  };
}

async function canUseTool(toolName, toolInput, meta = {}) {
  const id = "a" + ++seq;
  out({ ev: "approval", id, name: toolName, input: toolInput, requestId: meta.requestId });
  const ok = await new Promise((resolve) => approvals.set(id, resolve));
  return ok
    ? { behavior: "allow" }
    : { behavior: "deny", message: "declined by the user" };
}

async function open() {
  const client = new LettaAgentClient({ backend: "remote", url: LETTA_URL });
  let agentId = AGENT;
  if (!agentId) {
    agentId = await client.createAgent({
      name: "MalO",
      memory: [
        { label: "persona", value: PERSONA },
        { label: "human", value: "The user owns this machine and runs you on it." },
        { label: "journal", value: "(empty)" },
      ],
      permissionMode: perm,
      baseTools: BASE,
      skillSources: [],
    });
    out({ ev: "agent", agent: agentId });
  }
  session = CONV
    ? await client.resumeSession(CONV, {
        cwd: CWD, canUseTool, mcpServers: MCP,
        tools: TOOLS.map(pythonTool),
		permissionMode: perm,
		skillSources: [],
      })
    : await client.createSession(agentId, {
        cwd: CWD, canUseTool, mcpServers: MCP,
        tools: TOOLS.map(pythonTool),
		permissionMode: perm,
		skillSources: [],
      });
  out({ ev: "ready", agent: agentId, conversation: session.conversationId ?? "" });
}

async function turn(text) {
  running = true;
  const acc = new Map();
  try {
    await session.send(text);
    for await (const m of session.stream()) {
      if (m.type === "assistant" || m.type === "reasoning") {
        const kind = m.type === "assistant" ? "text" : "think";
        const key = kind + "|" + (m.otid ?? m.uuid ?? "x");
        const full = (acc.get(key) ?? "") + m.content;
        acc.set(key, full);
        out({ ev: kind, id: key, text: full });
      } else if (m.type === "tool_call") {
        out({ ev: "tool", id: m.toolCallId, name: m.toolName, input: null });
      } else if (m.type === "tool_result") {
        out({ ev: "result", id: m.toolCallId, ok: !m.isError,
              text: String(m.content).slice(0, 4000) });
      } else if (m.type === "queue_update") {
        out({ ev: "queue", n: m.queue?.length ?? 0 });
      } else if (m.type === "error") {
        out({ ev: "error", text: m.message + (m.errorDetail ? ": " + m.errorDetail : "") });
      } else if (m.type === "result") {
        out({ ev: "done", ok: m.success, stop: m.stopReason, code: m.errorCode ?? "",
              text: m.result ?? "" });
      }
    }
  } catch (e) {
    out({ ev: "error", text: String(e?.message ?? e) });
    out({ ev: "done", ok: false, stop: "error", code: "bridge", text: "" });
  } finally {
    running = false;
    if (queue.length) void turn(queue.shift());
  }
}

createInterface({ input: process.stdin }).on("line", async (line) => {
  let m;
  try { m = JSON.parse(line); } catch { return; }
  try {
    if (m.cmd === "init") return void open();
    if (m.cmd === "perm") {
      perm = m.mode || "standard";
      if (session) await session.changeDeviceState({ permissionMode: perm });
      return;
    }
    if (m.cmd === "approve") {
      const r = approvals.get(m.id);
      if (r) { approvals.delete(m.id); r(!!m.ok); }
      return;
    }
    if (m.cmd === "tool_result") {
      const r = inflight.get(m.id);
      if (r) { inflight.delete(m.id); r({ text: m.text, isError: !!m.error }); }
      return;
    }
    if (m.cmd === "abort") { if (session && running) await session.abort(); return; }
    if (m.cmd === "send") {
      if (!session) { out({ ev: "error", text: "session not open" }); return; }
      if (running) { queue.push(m.text); out({ ev: "queue", n: queue.length }); return; }
      return void turn(m.text);
    }
    if (m.cmd === "close") { session?.close(); out({ ev: "closed" }); process.exit(0); }
  } catch (e) {
    out({ ev: "error", text: String(e?.message ?? e) });
  }
});

process.on("SIGTERM", () => { session?.close(); process.exit(0); });
log("bridge up, url=" + LETTA_URL);