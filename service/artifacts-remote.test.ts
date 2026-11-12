import { expect, test } from "bun:test";
import { Artifacts } from "./artifacts.ts";

// PR 61 (Copilot's review, Nathan's call): an artifact file on another machine is read there through herdr-core once and
// kept a little while (media.ts keep()), so a player's part-by-part requests don't read the whole file there each time;
// a read herdr-core cut short is refused and never kept. The real Artifacts.file(), with a hub the test owns.
const bytes = (n: number, from = 0) => Uint8Array.from({ length: n }, (_, i) => (from + i) % 256);

function there(files: Record<string, Uint8Array>, cut = new Set<string>()) {
  const calls: string[] = [];
  const a = new Artifacts();
  a.hub = {
    // machine.exec on `on`: argv is sh -c SCRIPT file <id> <v> <rel>
    async call(method: string, p: { argv: string[]; on: string }) {
      if (method !== "machine.exec") throw new Error(method);
      const key = `${p.on}|${p.argv.slice(-3).join("|")}`;
      calls.push(key);
      const f = files[key];
      if (!f) return { code: 1, stdout: "", stderr: "" };
      return { code: 0, stdout: Buffer.from(f).toString("base64"), stderr: "", ...(cut.has(key) ? { truncated: true } : {}) };
    },
  } as never;
  return { a, calls };
}

const range = async (r: Response) => new Uint8Array(await r.arrayBuffer());

test("another machine's clip is read there once, then served part by part from what was kept", async () => {
  const clip = bytes(100);
  const { a, calls } = there({ "vm-a|keep-1|1|clip.mp4": clip });
  const first = await a.file("keep-1", 1, "clip.mp4", "vm-a", "bytes=10-19");
  expect(first.status).toBe(206);
  expect(first.headers.get("content-range")).toBe("bytes 10-19/100");
  expect([...(await range(first))]).toEqual([...clip.slice(10, 20)]);
  // the artifact's own sandboxed policy and no sniffing, on a part as on the whole file
  expect(first.headers.get("content-security-policy")).toBe("sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'");
  expect(first.headers.get("x-content-type-options")).toBe("nosniff");
  const second = await a.file("keep-1", 1, "clip.mp4", "vm-a", "bytes=90-");
  expect(second.status).toBe(206);
  expect([...(await range(second))]).toEqual([...clip.slice(90)]);
  expect(calls).toEqual(["vm-a|keep-1|1|clip.mp4"]);
});

test("what is kept is one machine's, one artifact's, one version's and one path's", async () => {
  const { a, calls } = there({
    "vm-a|keep-2|1|clip.mp4": bytes(8, 1), "vm-b|keep-2|1|clip.mp4": bytes(8, 50),
    "vm-a|keep-2|2|clip.mp4": bytes(8, 100), "vm-a|keep-2|1|other.mp4": bytes(8, 150),
  });
  const read = async (m: string, v: number, p: string) => [...(await range(await a.file("keep-2", v, p, m)))];
  expect(await read("vm-a", 1, "clip.mp4")).toEqual([...bytes(8, 1)]);
  expect(await read("vm-b", 1, "clip.mp4")).toEqual([...bytes(8, 50)]);
  expect(await read("vm-a", 2, "clip.mp4")).toEqual([...bytes(8, 100)]);
  expect(await read("vm-a", 1, "other.mp4")).toEqual([...bytes(8, 150)]);
  expect(calls.length).toBe(4);
});

test("a read herdr-core cut short is refused and not kept", async () => {
  const cut = new Set(["vm-a|keep-3|1|clip.mp4"]);
  const { a, calls } = there({ "vm-a|keep-3|1|clip.mp4": bytes(16) }, cut);
  const refused = await a.file("keep-3", 1, "clip.mp4", "vm-a", "bytes=0-3");
  expect(refused.status).toBe(404);
  // not kept: once herdr-core gives the whole file, it is read there again and served
  cut.clear();
  const whole = await a.file("keep-3", 1, "clip.mp4", "vm-a");
  expect(whole.status).toBe(200);
  expect([...(await range(whole))]).toEqual([...bytes(16)]);
  expect(calls).toEqual(["vm-a|keep-3|1|clip.mp4", "vm-a|keep-3|1|clip.mp4"]);
});
