// Restart Assistant (mods/chat/main.js restartAssistant, GitHub #1039) waits on hc get before it restarts anything.
// Meanwhile "Start a new one" stays pressable: it empties the chat (startFresh). The restart that was waiting must then
// stop, never resume a conversation the chat no longer holds; one left alone resumes the session it was pressed for.
import { expect, mock, test } from "bun:test";
import { fakeHerdr } from "./fake-herdr";
import { fakeGpuiBase, fakeGpuiKit } from "./fake-gpui";

const SESSION = "11111111-2222-3333-4444-555555555555";
const PATH = `/h/.claude/projects/x/${SESSION}.jsonl`;
const OLD = { address: "t7", state: "finished", argv: ["claude", "--model", "opus"], labels: {} };
// hc get answers when a test lets it; every exec (restart.sh runs through one) is kept
let getHeld: Promise<void> | null = null;
const execs: string[][] = [];
const notes: { title?: string }[] = [];
const hc = async (args: string[]) => {
  if (args[0] === "get") {
    if (getHeld) await getHeld;
    return { code: 0, stdout: JSON.stringify(OLD), stderr: "" };
  }
  return { code: 1, stdout: "", stderr: "" };
};
const exec = async (_cmd: string, args: string[]) => {
  execs.push(args);
  return { code: 0, stdout: "t8\n", stderr: "" };
};
mock.module("herdr", () => fakeHerdr({ exec, hc, agents: () => [], panes: () => [], terminals: () => [], spaces: () => [], machines: () => [], appHome: () => "/nonexistent-app",
  notify: (n: { title?: string }) => { notes.push(n); } }));
mock.module("gpui-kit", () => fakeGpuiKit());
mock.module("gpui-base", () => fakeGpuiBase());
(globalThis as any).localStorage ??= { getItem: () => null, setItem: () => {}, removeItem: () => {} };

const { default: Chat } = await import("../mods/chat/main.js");

// cx.spawn runs at once and keeps its promise, so a test can wait for the restart
let last: Promise<unknown> | null = null;
const cx: any = { spawn: (f: any) => { last = f(cx); }, notify: () => {}, timer: { after: () => {}, every: () => {} } };

function endedAssistant() {
  const chat: any = Object.create(Chat.prototype);
  Object.assign(chat, { addr: "t7", kind: "claude", path: PATH, argv: OLD.argv, endedAssistant: true, phase: "ended", role: "coordinator" });
  chat.myPane = () => "p1";
  chat.follow_to = (a: string) => { chat.followed = a; };
  chat.follow = async () => {};
  return chat;
}
const restarts = () => execs.filter((a) => a.some((x) => String(x).endsWith("/mods/coordinator/restart.sh")));

test("Start a new one while Restart Assistant waits: nothing restarts or fails, the chat stays fresh", async () => {
  execs.length = 0; notes.length = 0;
  let open = () => {};
  getHeld = new Promise((r) => { open = r; });
  try {
    const chat = endedAssistant();
    chat.restartAssistant(cx);
    const waiting = last;
    chat.startFresh();
    open(); await waiting;
    expect(restarts()).toEqual([]);
    expect(notes).toEqual([]);
    expect(chat.followed).toBeUndefined();
    expect(chat.phase).toBe("fresh");
    expect(chat.addr).toBeNull();
    expect(chat.restarting).toBe(false);
  } finally { getHeld = null; open(); }
});

test("left alone, Restart Assistant resumes the session it was pressed for", async () => {
  execs.length = 0; notes.length = 0;
  const chat = endedAssistant();
  chat.restartAssistant(cx);
  await last;
  const [run] = restarts();
  expect(run).toBeDefined();
  expect(JSON.parse(run.at(-1)!)).toEqual(["claude", "--model", "opus", "--resume", SESSION]);
  expect(chat.followed).toBe("t8");
  expect(notes).toEqual([]);
});
