// PR 60: the window's "#" list (mods/chat/main.js loadReach) for a chat whose agent runs on another machine. That
// machine's reach map starts there; the window's own spaces (no machine) must go under this machine's herdr-core name,
// with the route to it, never as the agent's machine's own; and a machine whose document the map read as empty still
// lists the spaces the window knows there (SHEP-185).
import { expect, mock, test } from "bun:test";
import { fakeHerdr } from "./fake-herdr";
import { fakeGpuiBase, fakeGpuiKit } from "./fake-gpui";

// vm-a's map: it reaches mini (this machine) over herdr-core and vm-b over ssh; both documents read as empty
const VM_A = {
  core: { id: "c-a", name: "vm-a" }, host: "vm-a", spaces: [{ id: "spA1", name: "api" }], assistants: [],
  links: [
    { how: "herdr-core", to: "mini", ok: true, id: "c-mini", next: { core: { id: "c-mini", name: "mini" }, spaces: [], links: [] } },
    { how: "ssh", to: "vm-b", ok: true, id: "c-b", next: { core: { id: "c-b", name: "vm-b" }, spaces: [], links: [] } },
  ],
};
// mini's own map, for a chat whose agent runs here
const MINI = { core: { id: "c-mini", name: "mini" }, host: "mini", spaces: [], assistants: [], links: [] };
// the spaces the window knows: its own have no machine
const SPACES = [
  { id: "spMINI", name: "shop", folder: "/m/shop", machine: null, tabs: [] },
  { id: "spA2", name: "docs", folder: "/a/docs", machine: "vm-a", tabs: [] },
  { id: "spB1", name: "lab", folder: "/b/lab", machine: "vm-b", tabs: [] },
];
const maps: Record<string, unknown> = { "vm-a": VM_A, "": MINI };
const exec = async (_cmd: string, _args: string[], opt?: { on?: string | null }) =>
  ({ code: 0, stdout: JSON.stringify({ graph: maps[opt?.on ?? ""], at: 1 }), stderr: "" });
const hc = async (args: string[]) =>
  args.join(" ") === "server status" ? { code: 0, stdout: JSON.stringify({ core: { name: "mini" } }), stderr: "" } : { code: 1, stdout: "", stderr: "" };
mock.module("herdr", () => fakeHerdr({ exec, hc, agents: () => [], panes: () => [], terminals: () => [], spaces: () => SPACES, machines: () => [] }));
mock.module("gpui-kit", () => fakeGpuiKit());
mock.module("gpui-base", () => fakeGpuiBase());
(globalThis as any).localStorage ??= { getItem: () => null, setItem: () => {}, removeItem: () => {} };

const { default: Chat } = await import("../mods/chat/main.js");
const rows = (list: any[]) => list.map((s) => [s.id, s.route, s.machine, s.target]);

test("a remote agent's # list puts the window's own spaces under this machine, with their route", async () => {
  const chat: any = Object.create(Chat.prototype);
  chat.machine = "vm-a";
  await chat.loadReach();
  expect(chat.reach.from).toBe("vm-a");
  expect(rows(chat.reach.spaces)).toEqual([
    ["spA1", "", "vm-a", "spA1"],
    ["spA2", "", "vm-a", "spA2"],
    ["spMINI", "mini", "mini", "mini/spMINI"],
    ["spB1", "vm-b", "vm-b", "vm-b/spB1"],
  ]);
});

test("an agent on this machine lists the window's own spaces as its own", async () => {
  const chat: any = Object.create(Chat.prototype);
  chat.machine = null;
  await chat.loadReach();
  expect(chat.reach.from).toBe("mini");
  expect(rows(chat.reach.spaces)).toEqual([["spMINI", "", "mini", "spMINI"]]);
});
