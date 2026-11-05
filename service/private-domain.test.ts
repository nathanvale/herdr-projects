import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:net";
import { request } from "node:https";
import { readPrivateDomain, servePrivateDomain, type PrivateDomain } from "./private-domain.ts";
import type { Gate } from "./auth.ts";

const root = mkdtempSync(join(tmpdir(), "shepherdr-private-domain-"));
const modeFile = join(root, "identity.json");
const certFile = join(root, "cert.pem"), keyFile = join(root, "key.pem");
const state: Gate = { owner: "owner@example.test", dns: "device.tailnet.example", port: 7788, token: "test-local-token" };
let server: Awaited<ReturnType<typeof servePrivateDomain<{ who: string }>>>;
let config: PrivateDomain;
let reached = 0;

function identity(change: Record<string, unknown> = {}) {
  writeFileSync(modeFile, JSON.stringify({ login: "owner@example.test", addresses: ["127.0.0.1/32"], ...change }));
}

// Connect to a real loopback TLS socket with a test-owned CA and DNS server name. Only Tailscale's CLI is a fixture.
function call(method = "GET", headers: Record<string, string> = {}, upgrade = false): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = request({
      hostname: "127.0.0.1", port: server.port, servername: "app.example.test", ca: readFileSync(certFile),
      path: upgrade ? "/shepherdr/api/ws" : "/shepherdr/api/proof", method,
      headers: { host: new URL(config.origin).host, ...headers },
    }, (res) => { res.resume(); res.on("end", () => resolve(res.statusCode!)); });
    req.on("upgrade", (res, socket) => { socket.destroy(); resolve(res.statusCode!); });
    req.on("error", reject);
    req.end();
  });
}

beforeAll(async () => {
  const cert = Bun.spawnSync(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
    "-keyout", keyFile, "-out", certFile, "-subj", "/CN=app.example.test", "-addext", "subjectAltName=DNS:app.example.test"],
    { stdout: "ignore", stderr: "ignore" });
  if (cert.exitCode !== 0) throw new Error("Test certificate generation failed.");
  chmodSync(keyFile, 0o600);
  const command = join(root, "tailscale");
  writeFileSync(command, `#!/usr/bin/env bun
import { readFileSync } from 'node:fs';
const m = JSON.parse(readFileSync(${JSON.stringify(modeFile)}, 'utf8'));
if (process.argv[2] === 'status') console.log(JSON.stringify({
  BackendState: m.stopped ? 'Stopped' : 'Running',
  Self: { Online: true, UserID: 1, TailscaleIPs: ['127.0.0.1'], Tags: [] },
  User: { '1': { LoginName: 'owner@example.test' } }
}));
else {
  if (m.failure) process.exit(1);
  console.log(JSON.stringify({Node: {Addresses: m.addresses, Tags: m.tagged ? ['tag:server'] : []}, UserProfile: {LoginName: m.login}}));
}
`, { mode: 0o700 });
  identity();
  const listener = createServer();
  await new Promise<void>((r) => listener.listen(0, "127.0.0.1", r));
  const address = listener.address();
  if (!address || typeof address === "string") throw new Error("No test port.");
  const port = address.port;
  await new Promise<void>((r, j) => listener.close((e) => e ? j(e) : r()));
  config = { origin: `https://app.example.test:${port}`, bind: "127.0.0.1", certificate: certFile, key: keyFile, tailscale: command };
  // Loopback stands in for an OS-owned Tailscale interface only in this composition; the public config parser refuses it.
  server = await servePrivateDomain<{ who: string }>(config, () => state, {
    fetch(req, srv, pass) {
      reached++;
      if (new URL(req.url).pathname.endsWith("/ws")) {
        return srv.upgrade(req, { data: { who: pass.who } }) ? undefined : new Response("upgrade failed", { status: 400 });
      }
      return Response.json({ who: pass.who });
    },
    websocket: { message() {} },
  });
});
afterAll(async () => { if (server) await server.stop(true); rmSync(root, { recursive: true, force: true }); });

describe("private HTTPS across a real TLS listener", () => {
  test("the verified owner reads and writes on the configured origin", async () => {
    identity();
    expect(await call()).toBe(200);
    expect(await call("POST", { origin: config.origin, "x-shepherdr": "1" })).toBe(200);
  });
  test("another identity cannot reach the handler, even with forged identity headers and local token", async () => {
    identity({ login: "other@example.test" }); const before = reached;
    expect(await call("GET", { "tailscale-user-login": "owner@example.test", "x-forwarded-for": "100.64.0.1", authorization: "Bearer test-local-token" })).toBe(403);
    expect(reached).toBe(before);
  });
  test("a tagged node cannot use its user's profile to enter", async () => {
    identity({ tagged: true }); const before = reached;
    expect(await call()).toBe(403); expect(reached).toBe(before);
  });
  test("unresolved and nonmatching peer evidence refuse without handler effects", async () => {
    const before = reached;
    identity({ failure: true }); expect(await call()).toBe(403);
    identity({ addresses: ["100.64.0.99/32"] }); expect(await call()).toBe(403);
    expect(reached).toBe(before);
  });
  test("stopped Tailscale and changed owner cannot reuse an earlier grant", async () => {
    identity(); expect(await call()).toBe(200); const before = reached;
    identity({ stopped: true }); expect(await call()).toBe(503);
    identity(); state.owner = "different@example.test";
    try { expect(await call()).toBe(503); } finally { state.owner = "owner@example.test"; }
    expect(reached).toBe(before);
  });
  test("hostname, origin, preflight and CSRF refusals happen before the handler", async () => {
    identity(); const before = reached;
    expect(await call("GET", { host: "other.example.test" })).toBe(421);
    expect(await call("POST", { origin: "https://other.example.test", "x-shepherdr": "1" })).toBe(403);
    expect(await call("POST", { origin: config.origin })).toBe(403);
    expect(await call("GET", { "sec-fetch-site": "cross-site" })).toBe(403);
    expect(await call("OPTIONS", { origin: config.origin })).toBe(403);
    expect(reached).toBe(before);
  });
  test("WebSocket upgrades require the same owner and exact browser origin", async () => {
    const headers = { connection: "Upgrade", upgrade: "websocket", "sec-websocket-version": "13", "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ==", origin: config.origin };
    identity(); expect(await call("GET", headers, true)).toBe(101);
    const before = reached;
    expect(await call("GET", { ...headers, origin: "https://other.example.test" }, true)).toBe(403);
    identity({ login: "other@example.test" }); expect(await call("GET", headers, true)).toBe(403);
    expect(reached).toBe(before);
  });
  test("a nonlocal binding and unsafe private key cannot start a listener", async () => {
    identity();
    const handlers = { fetch: () => new Response("must not open"), websocket: { message() {} } };
    await expect(servePrivateDomain({ ...config, bind: "100.64.0.99" }, () => state, handlers)).rejects.toThrow("exact local address");
    chmodSync(keyFile, 0o644);
    try { await expect(servePrivateDomain(config, () => state, handlers)).rejects.toThrow("private key"); }
    finally { chmodSync(keyFile, 0o600); }
    await expect(servePrivateDomain(config, () => state, handlers)).rejects.toThrow("Private HTTPS could not start on its configured address and port.");
    expect(await call()).toBe(200); // The original listener survives an occupied-port refusal.
  });
});

test("configuration is opt-in and rejects unsafe or ambiguous origins", () => {
  expect(readPrivateDomain(undefined)).toBeNull();
  const file = join(root, "config.json");
  const good = { origin: "https://app.example.test", bind: "100.64.0.1", certificate: certFile, key: keyFile };
  writeFileSync(file, JSON.stringify(good)); expect(readPrivateDomain(file)).toEqual(good);
  for (const change of [
    { origin: "http://app.example.test" }, { origin: "https://owner:password@app.example.test" },
    { origin: "https://app.example.test/path" }, { origin: "https://app.example.test?token=hidden" },
    { origin: "https://app.example.test:0" }, { origin: "https://app.example.test." },
    { bind: "0.0.0.0" }, { bind: "127.0.0.1" }, { bypass: true },
  ]) {
    writeFileSync(file, JSON.stringify({ ...good, ...change })); expect(() => readPrivateDomain(file)).toThrow();
  }
});
