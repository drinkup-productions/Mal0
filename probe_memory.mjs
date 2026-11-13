// What tools exist? Ask her to enumerate them, then test memory.
import { LettaAgentClient } from "@letta-ai/letta-agent-sdk";

const client = new LettaAgentClient({ backend: "remote", url: "ws://127.0.0.1:4500" });

const agentId = await client.createAgent({
  name: "memory probe",
  memory: [
    { label: "persona", value: "probe" },
    { label: "human", value: "probe" },
    { label: "notes", value: "(empty)" },
  ],
  permissionMode: "unrestricted",
  baseTools: ["Read", "Write", "Bash"],
});

console.log("agent:", agentId);

await using session = client.createSession(agentId, {
  cwd: process.cwd(),
  permissionMode: "unrestricted",
  canUseTool: async () => ({ behavior: "allow" }),
});

await session.send(
  "Run exactly this in CodeMode: await tools.listTools()\n" +
  "Print every tool name it returns, one per line, verbatim. Nothing else.\n" +
  "Then append 'probe-write-ok' to your notes block with whatever memory tool you " +
  "have and read it back. If there is no memory tool, say NO MEMORY TOOL.",
);

for await (const m of session.stream()) {
  if (m.type === "tool_call") console.log("TOOL:", m.toolName, (m.rawArguments ?? "").slice(0, 100));
  if (m.type === "tool_result") console.log("  <-", String(m.content).slice(0, 1200));
  if (m.type === "assistant") process.stdout.write(m.content);
  if (m.type === "error") console.error("\nERR:", m.message);
  if (m.type === "result") console.log("\nstop=" + m.stopReason + " ok=" + m.success + " code=" + (m.errorCode ?? ""));
}