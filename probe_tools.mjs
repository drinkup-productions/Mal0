// Prints the full tool list for a fresh session. Diagnostics only.
import { LettaAgentClient } from "@letta-ai/letta-agent-sdk";

const client = new LettaAgentClient({ backend: "remote", url: "ws://127.0.0.1:4500" });

const agentId = await client.createAgent({
  name: "tools probe",
  memory: [
    { label: "persona", value: "probe" },
    { label: "human", value: "probe" },
    { label: "journal", value: "(empty)" },
    { label: "notes", value: "(empty)" },
  ],
  permissionMode: "unrestricted",
});

await using session = client.createSession(agentId, { cwd: process.cwd() });
const st = await session.bootstrapState();
const names = (st?.tools ?? []).map((t) => (typeof t === "string" ? t : t.name ?? t.id));
console.log(names.sort().join("\n"));
console.log("\ncount:", names.length);
console.log("blocks:", JSON.stringify(st?.memoryBlocks ?? st?.blocks ?? null));