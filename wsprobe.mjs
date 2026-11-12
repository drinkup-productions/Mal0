// Diagnostics only. Reports whether the App Server is reachable and at what path.
const base = process.argv[2] ?? "http://127.0.0.1:4500";
const key = Buffer.from(crypto.randomUUID()).toString("base64");

for (const u of [base + "/", base + "/ws"]) {
  try {
    const r = await fetch(u, {
      headers: { connection: "Upgrade", upgrade: "websocket",
                 "sec-websocket-key": key, "sec-websocket-version": "13" },
    });
    console.log(u, "->", r.status, "upgrade=" + (r.headers.get("upgrade") ?? "-"));
  } catch (e) {
    console.log(u, "-> FAIL", e.cause?.code ?? e.message);
  }
}

for (const u of [base.replace("http", "ws") + "/ws", base.replace("http", "ws")]) {
  await new Promise((done) => {
    const ws = new WebSocket(u);
    const t = setTimeout(() => { console.log(u, "-> timeout"); ws.close(); done(); }, 4000);
    ws.onopen = () => { clearTimeout(t); console.log(u, "-> OPEN"); ws.close(); done(); };
    ws.onerror = () => {};
    ws.onclose = (e) => { clearTimeout(t); console.log(u, "-> close", e.code, e.reason); done(); };
  });
}