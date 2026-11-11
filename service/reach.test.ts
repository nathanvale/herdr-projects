// PR 60 #1: the service's "#" list (/api/reach: service/reach.ts), run as the service runs it: the real Host learns
// this machine's herdr-core name from the core, the real Compat knows the spaces from a snapshot, and each machine's
// reach map comes back over the core's machine.exec. Only the core is a stand-in (this file's hub), never a service.
import { expect, test } from "bun:test";
import { Host } from "./host.ts";
import { Compat } from "./compat.ts";
import { Reach } from "./reach.ts";

// vm-a's map: it reaches mini (this machine) over herdr-core and vm-b over ssh; both documents read as empty
const VM_A = {
  core: { id: "c-a", name: "vm-a" }, host: "vm-a", spaces: [{ id: "spA1", name: "api" }], assistants: [],
  links: [
    { how: "herdr-core", to: "mini", ok: true, id: "c-mini", next: { core: { id: "c-mini", name: "mini" }, spaces: [], links: [] } },
    { how: "ssh", to: "vm-b", ok: true, id: "c-b", next: { core: { id: "c-b", name: "vm-b" }, spaces: [], links: [] } },
  ],
};
// mini's own map: it reaches vm-a over herdr-core, whose document reads as empty
const MINI = {
  core: { id: "c-mini", name: "mini" }, host: "mini", spaces: [], assistants: [],
  links: [{ how: "herdr-core", to: "vm-a", ok: true, id: "c-a", next: { core: { id: "c-a", name: "vm-a" }, spaces: [], links: [] } }],
};
// the spaces the service knows: its own (no machine) with its Assistant here, docs with its Assistant on vm-a, and
// lab on vm-b with no agent yet
const SPACES = [
  { id: "spMINI", name: "shop", folder: "/m/shop", machine: null, assistant: "t1", tabs: [] },
  { id: "vm-a/spA2", name: "docs", folder: "/a/docs", machine: "vm-a", assistant: "vm-a/t5", tabs: [] },
  { id: "vm-b/spB1", name: "lab", folder: "/b/lab", machine: "vm-b", tabs: [] },
];

// The core here: this machine is "mini"; machine.exec reads the named machine's map (no on: this machine's). A map
// that is "unreachable" fails as the core fails; one that is missing reads as nothing. Each exec's machine is kept.
async function world(maps: Record<string, object | "unreachable" | null>) {
  const asked: (string | null)[] = [];
  const b64 = (t: string) => Buffer.from(t).toString("base64");
  const hub = {
    terminals: new Map(),
    on() { return () => {}; },
    async call(method: string, p: any = {}) {
      if (method === "server.status") return { core: { id: "c-mini", name: "mini" } };
      if (method === "machine.list") return { machines: [] };
      if (method === "doc.get") return { value: null, version: 0 };
      if (method === "doc.set") return { version: 1 };
      if (method === "machine.exec") {
        asked.push(p.on ?? null);
        const m = maps[p.on ?? ""];
        if (m === "unreachable") throw Object.assign(new Error("unreachable"), { kind: "unavailable" });
        return { code: 0, stdout: b64(m ? JSON.stringify({ graph: m, at: 1 }) : ""), stderr: "" };
      }
      throw new Error(`no ${method}`);
    },
  };
  const host = new Host(hub as any, "t");
  await host.poll();
  const compat = new Compat() as any;
  compat.snapshot({ host: "mini", user: "me", machines: [], spaces: SPACES, sections: [], rows: [] });
  // this machine's tailnet name (tailscale.ts whoami), apart from its herdr-core name
  const reach = new Reach(hub as any, host, compat, () => ({ login: "me", name: "Me", dns: "mini-ts.tail.net", host: "mini-ts" }));
  return { reach, asked };
}
const rows = (list: any[]) => list.map((s) => [s.id, s.name, s.route, s.machine, s.target]);

test("a remote agent's # list from the service puts its own spaces under this machine, with their route", async () => {
  const { reach, asked } = await world({ "vm-a": VM_A, "": MINI });
  const got = await reach.forChat("p:vm-a:spA2");
  expect(got.from).toBe("vm-a");
  expect(got.checked).toBe(1);
  expect(rows(got.spaces)).toEqual([
    ["spA1", "api", "", "vm-a", "spA1"],
    ["spA2", "docs", "", "vm-a", "spA2"],
    ["spMINI", "shop", "mini", "mini", "mini/spMINI"],
    ["spB1", "lab", "vm-b", "vm-b", "vm-b/spB1"],
  ]);
  // kept a minute: the same machine's list again asks the core nothing more
  await reach.forChat("p:vm-a:spA2");
  expect(asked).toEqual(["vm-a"]);
});

test("an agent on this machine gets the service's own spaces as its own", async () => {
  const { reach, asked } = await world({ "vm-a": VM_A, "": MINI });
  const got = await reach.forChat("p:spMINI");
  expect(asked).toEqual([null]);
  expect(got.from).toBe("mini");
  expect(rows(got.spaces)).toEqual([
    ["spMINI", "shop", "", "mini", "spMINI"],
    ["spA2", "docs", "vm-a", "vm-a", "vm-a/spA2"],
  ]);
});

test("a chat with no agent yet uses its space's machine, and with no map there lists that machine's own spaces", async () => {
  const { reach, asked } = await world({ "vm-a": VM_A, "": MINI, "vm-b": "unreachable" });
  const got = await reach.forChat("p:vm-b:spB1");
  expect(asked).toEqual(["vm-b"]);
  expect(got).toEqual({ from: "vm-b", checked: null, spaces: [{ id: "spB1", name: "lab", route: "", machine: "vm-b", target: "spB1", assistant: false }] });
});

test("with no map drawn here yet, this machine's own spaces carry its tailnet name", async () => {
  const { reach } = await world({ "": null });
  const got = await reach.forChat("p:spMINI");
  expect(got).toEqual({ from: null, checked: null, spaces: [{ id: "spMINI", name: "shop", route: "", machine: "mini-ts", target: "spMINI", assistant: true }] });
});
