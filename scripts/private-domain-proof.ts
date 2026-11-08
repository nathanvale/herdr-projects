// Read-only native transport qualification. Does not import main.ts, core, tasks, settings, or scheduler.
import { readPrivateDomain, servePrivateDomain } from "../service/private-domain.ts";
import { whoami } from "../service/tailscale.ts";
import type { Gate } from "../service/auth.ts";

const config = readPrivateDomain(process.argv[2]);
if (!config) throw new Error("Pass the private HTTPS configuration file.");
const me = await whoami();
const owner: Gate = { owner: me?.login ?? null, dns: me?.dns ?? null, port: 0, token: "" };
const server = await servePrivateDomain<{ who: string }>(config, () => owner, {
  fetch(req, srv, pass) {
    if (new URL(req.url).pathname === "/shepherdr/api/ws") {
      return srv.upgrade(req, { data: { who: pass.who } }) ? undefined : new Response("Upgrade failed.", { status: 400 });
    }
    return Response.json({ ok: true, proof: "private-domain-transport-only", method: req.method });
  },
  websocket: { open(ws) { ws.send("private-domain-transport-only"); }, message() {} },
});
console.log(JSON.stringify({ ready: true, origin: config.origin, proof: "private-domain-transport-only", port: server.port }));
for (const signal of ["SIGTERM", "SIGINT"] as const) process.on(signal, () => { server.stop(true); process.exit(0); });
