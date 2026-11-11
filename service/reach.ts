// The "#" list above a chat's box (core/mentions.js): the spaces the machine running the chat's agent can reach, from
// that machine's herdr-task reach map (what tell-assistant follows). Its own module so a test can run the service's
// caller with a stand-in herdr-core (service/reach.test.ts); service/main.ts serves it at /api/reach.
import type { Hub } from "./hub.ts";
import type { Host } from "./host.ts";
import { placeKey, type Compat } from "./compat.ts";
import type { Me } from "./tailscale.ts";
import { exec } from "./model.ts";
import * as MN from "../core/mentions.js";
const { REACH_FILE, reachIn } = MN as any;

export type ReachList = { from: string | null; spaces: any[]; checked: number | null };

export class Reach {
  // a machine's reach map, as its spaces: kept a minute (its scheduler redraws it every 5)
  private reaches = new Map<string, { at: number; got: Promise<ReachList> }>();

  constructor(private hub: Hub, private host: Host, private compat: Compat, private me: () => Me | null) {}

  /** The list for a chat: the machine running its agent; a chat with no agent yet: its space's machine. */
  forChat(key: string) {
    const a = this.compat.addrOf(key);
    const sp = !a ? this.compat.allSpaces().find((s) => placeKey(s.id) === key) : null;
    return this.of(a ? (a.includes("/") ? a.split("/")[0] : null) : sp?.machine ?? null);
  }

  // The spaces the service already knows (the sidebar's list, each with its place's name): a reach map that reads a
  // machine's document as empty still lists them (core/mentions.js reachable, SHEP-185).
  private knownSpaces() {
    const { compat } = this;
    return compat.allSpaces().map((s) => {
      const p = compat.last?.places.find((x) => x.id === s.id);
      return { id: s.id.split("/").pop()!, name: p?.name ?? "", folder: s.folder, machine: s.machine ?? null, ...(p?.emoji ? { emoji: p.emoji } : {}), assistant: !!p?.assistantTab?.live };
    });
  }

  private of(machine: string | null): Promise<ReachList> {
    const { compat } = this;
    const k = machine ?? "", was = this.reaches.get(k);
    if (was && Date.now() - was.at < 60_000) return was.got;
    const got = exec(this.hub, ["sh", "-c", REACH_FILE], machine, 20).then((r) => {
      // the map starts on the agent's machine: the service's own spaces go under its herdr-core name there (PR 60)
      return reachIn(JSON.parse(r.stdout || "null"), this.knownSpaces(), this.host.me?.name || null, machine);
    }).catch(() => null).then((r) => r?.checked ? r : {
      // no map there yet (its scheduler hasn't run): its own spaces, which it always reaches
      from: machine, checked: null,
      spaces: compat.allSpaces().filter((s) => (s.machine ?? null) === machine).map((s) => {
        const id = s.id.split("/").pop()!, p = compat.last?.places.find((x) => x.id === s.id);
        return { id, name: p?.name ?? id, route: "", machine: machine ?? this.me()?.host ?? "", target: id, ...(p?.emoji ? { emoji: p.emoji } : {}), assistant: !!p?.assistantTab?.live };
      }),
    });
    this.reaches.set(k, { at: Date.now(), got });
    return got;
  }
}
