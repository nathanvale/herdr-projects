// Optional private HTTPS, authenticated by the actual Tailscale TCP peer. No proxy identity headers.
import { readFileSync, statSync } from "node:fs";
import { isIP } from "node:net";
import { createPrivateKey, X509Certificate } from "node:crypto";
import { gate, type Gate, type Pass } from "./auth.ts";

export type PrivateDomain = { origin: string; bind: string; certificate: string; key: string; tailscale?: string };
export type Admitted = Extract<Pass, { ok: true }>;
export type PrivateHandlers<T> = {
  fetch(req: Request, server: Bun.Server<T>, admitted: Admitted): Response | undefined | Promise<Response | undefined>;
  websocket: Bun.WebSocketHandler<T>;
};

/** Explicit opt-in, outside shared settings. Key/cert values never enter the configuration. */
export function readPrivateDomain(file: string | undefined): PrivateDomain | null {
  if (!file) return null;
  let value: any;
  try { value = JSON.parse(readFileSync(file, "utf8")); } catch { throw new Error("Private HTTPS configuration cannot be read."); }
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).some((k) => !["origin", "bind", "certificate", "key", "tailscale"].includes(k))) {
    throw new Error("Private HTTPS configuration has unknown fields.");
  }
  for (const k of ["origin", "bind", "certificate", "key"]) {
    if (typeof value[k] !== "string" || !value[k]) throw new Error(`Private HTTPS requires ${k}.`);
  }
  let url: URL;
  try { url = new URL(value.origin); } catch { throw new Error("Private HTTPS requires an HTTPS origin."); }
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash ||
      !url.hostname.includes(".") || url.hostname.length > 253 ||
      !url.hostname.split(".").every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label)) ||
      isIP(url.hostname) || url.port === "0") {
    throw new Error("Private HTTPS requires one DNS hostname, with no path or credentials.");
  }
  if (!isIP(value.bind) || ["0.0.0.0", "::", "127.0.0.1", "::1"].includes(value.bind)) {
    throw new Error("Private HTTPS must bind an exact local Tailscale address.");
  }
  if (value.tailscale !== undefined && (typeof value.tailscale !== "string" || !value.tailscale)) {
    throw new Error("Private HTTPS tailscale must be an executable name or path.");
  }
  return { ...value, origin: url.origin };
}

// Fail closed and keep command output (which can contain device/account details) out of errors.
async function query(command: string, args: string[]): Promise<any | null> {
  try {
    const p = Bun.spawn([command, ...args], { stdout: "pipe", stderr: "ignore", stdin: "ignore" });
    const timer = setTimeout(() => p.kill(), 3000);
    try {
      const out = await new Response(p.stdout).text();
      if ((await p.exited) !== 0 || out.length > 1024 * 1024) return null;
      return JSON.parse(out);
    } finally { clearTimeout(timer); }
  } catch { return null; }
}

function localOwner(status: any, config: PrivateDomain, owner: string | null): boolean {
  const self = status?.Self;
  const user = status?.User?.[String(self?.UserID)];
  return !!owner && status?.BackendState === "Running" && self?.Online === true &&
    Array.isArray(self?.TailscaleIPs) && self.TailscaleIPs.includes(config.bind) &&
    !(self.Tags?.length) && user?.LoginName === owner;
}

function certificate(config: PrivateDomain) {
  try {
    const permissions = statSync(config.key);
    if (!permissions.isFile() || (permissions.mode & 0o077) !== 0) throw new Error();
    const key = readFileSync(config.key);
    const cert = readFileSync(config.certificate);
    const x509 = new X509Certificate(cert);
    const now = Date.now();
    if (!x509.checkHost(new URL(config.origin).hostname) || !x509.checkPrivateKey(createPrivateKey(key)) ||
        Date.parse(x509.validFrom) > now || Date.parse(x509.validTo) <= now) throw new Error();
    return { key, cert, serverName: new URL(config.origin).hostname };
  } catch { throw new Error("Private HTTPS needs a current matching certificate and a private key readable only by its owner."); }
}

/** Starts only after local ownership and TLS validation. Uses the same fetch/WebSocket handlers as the service. */
export async function servePrivateDomain<T>(config: PrivateDomain, current: () => Gate, handlers: PrivateHandlers<T>) {
  const command = config.tailscale || "tailscale";
  if (!localOwner(await query(command, ["status", "--json"]), config, current().owner)) {
    throw new Error("Private HTTPS requires this owner's running Tailscale node and its exact local address.");
  }
  const tls = certificate(config);
  const pending = new Map<string, Promise<{ status: any; peer: any }>>();
  const identity = (address: string) => {
    let result = pending.get(address);
    if (!result) {
      result = Promise.all([query(command, ["status", "--json"]), query(command, ["whois", "--json", address])])
        .then(([status, peer]) => ({ status, peer }));
      pending.set(address, result);
      void result.finally(() => { if (pending.get(address) === result) pending.delete(address); });
    }
    return result;
  };
  return Bun.serve<T>({
    hostname: config.bind,
    port: Number(new URL(config.origin).port || 443),
    tls,
    async fetch(req, server) {
      const address = server.requestIP(req)?.address.replace(/^::ffff:/, "");
      if (!address || !isIP(address)) return new Response("No Tailscale peer.", { status: 403 });
      const owner = current().owner;
      const { status, peer } = await identity(address);
      // No cached grants: coalesce concurrent lookups only. An owner switch during lookup cannot admit a request.
      if (current().owner !== owner || !localOwner(status, config, owner)) {
        return new Response("Tailscale ownership is unavailable.", { status: 503 });
      }
      const addresses = peer?.Node?.Addresses;
      const exact = Array.isArray(addresses) && addresses.some((a: unknown) => a === `${address}/${isIP(address) === 4 ? 32 : 128}`);
      const login = exact && !(peer?.Node?.Tags?.length) ? peer?.UserProfile?.LoginName : null;
      const path = new URL(req.url).pathname;
      const socket = ["ws", "terminal", "browser", "voice"].some((p) => path === `/api/${p}` || path === `/shepherdr/api/${p}`);
      const pass = gate(req, current(), socket, false, { origin: config.origin, login: typeof login === "string" ? login : null });
      if (!pass.ok) return new Response(pass.why, { status: pass.status, headers: { "cache-control": "no-store" } });
      return handlers.fetch(req, server, pass);
    },
    websocket: handlers.websocket,
  });
}
