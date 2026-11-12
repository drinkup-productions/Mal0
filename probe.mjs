// De-risk only. One task, five steps, real tools, no UI.
// Usage: $env:MALO_URL="ws://127.0.0.1:4500"; node probe.mjs
import { readFileSync } from "node:fs";
import { LettaAgentClient } from "@letta-ai/letta-agent-sdk";

function wsUrl(raw) {
  const p = new URL(raw);
  p.protocol = (p.protocol === "https:" || p.protocol === "wss:") ? "wss:" : "ws:";
  if (!p.pathname || p.pathname === "/") p.pathname = "/ws";
  return p.toString();
}

const LETTA_URL = wsUrl(process.env.MALO_URL ?? "ws://127.0.0.1:4500");
const MCP = JSON.parse(readFileSync(new URL("./mcp_servers.json", import.meta.url), "utf8"));

const PERSONA =
  "You are MalO: a purple-furred anthro wolf girl with a long spiky lavender mane, " +
  "a white bone skull mask, a white cropped tank and black cargo shorts. Curious, " +
  "a little eerie, quietly fond of the user. You operate this machine with tools.";
const HUMAN = "The user owns this machine and runs you on it. Be brief and concrete.";

console.log("url:", LETTA_URL);

const client = new LettaAgentClient({ backend: "remote", url: LETTA_URL });

const agentId = await client.createAgent({
  name: "MalO probe",
  memory: [
    { label: "persona", value: PERSONA },
    { label: "human", value: HUMAN },
    { label: "journal", value: "(empty)" },
  ],
  permissionMode: "unrestricted",
});

console.log("agent:", agentId);

await using session = client.createSession(agentId, {
  cwd: process.cwd(),
  permissionMode: "unrestricted",
  canUseTool: async (toolName, toolInput) => {
    console.log("\n  ?? approve " + toolName + " " + JSON.stringify(toolInput).slice(0, 120));
    return { behavior: "allow" };
  },
  mcpServers: { ddg: MCP.ddg },
});

try {
  const st = await session.bootstrapState();
  const names = (st?.tools ?? []).map((t) => (typeof t === "string" ? t : t.name ?? t.id));
  console.log("tools visible:", names.length ? names.join(", ") : "(none)");
} catch (e) {
  console.log("bootstrapState failed:", e?.message ?? e);
}

await session.send(
  "Do all five, in order, and tell me the result of each:\n" +
  "1. search for 'windows media ocr powershell'\n" +
  "2. fetch the top non-DuckDuckGo result\n" +
  "3. write the page title to probe_out.txt\n" +
  "4. read probe_out.txt back\n" +
  "5. say done",
);

for await (const m of session.stream()) {
  if (m.type === "init") console.log("init:", JSON.stringify(m).slice(0, 400));
  if (m.type === "reasoning") process.stdout.write("\x1b[2m" + m.content + "\x1b[0m");
  if (m.type === "assistant") process.stdout.write(m.content);
  if (m.type === "tool_call") console.log("\n  -> " + m.toolName + " " + (m.rawArguments ?? ""));
  if (m.type === "tool_result") console.log("  <- " + String(m.content).slice(0, 200));
  if (m.type === "error") console.error("\nERROR " + m.message + " " + (m.errorDetail ?? ""));
  if (m.type === "result") {
    console.log("\n\nstop=" + m.stopReason + " ok=" + m.success + " ms=" + m.durationMs);
    if (!m.success) console.log("code=" + m.errorCode);
  }
}