import { afterAll, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SCAN, scanned } from "./slash.js";

// The "/" list's scan of the agent's machine (service/main.ts runs SCAN with sh). Claude Code shows an installed,
// enabled plugin's skills and commands as /plugin:name; the chat's list must offer them too, read where Claude reads
// them (CLAUDE_CONFIG_DIR, else ~/.claude), and leave out a plugin that is installed but switched off.
const root = mkdtempSync(join(tmpdir(), "slash-scan-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));
const put = (path, text) => { mkdirSync(join(path, ".."), { recursive: true }); writeFileSync(path, text); };
const skill = (dir, name, about) => put(join(dir, name, "SKILL.md"), `---\nname: ${name}\ndescription: ${about}\n---\n# ${name}\n`);

function home(configDir) {
  const ce = join(configDir, "plugins/cache/ce-market/compound-engineering/3.37.0");
  skill(join(ce, "skills"), "ce-plan", "Create structured plans");
  put(join(ce, "commands/lfg.md"), "---\ndescription: Ship it end to end\n---\nGo.\n");
  const off = join(configDir, "plugins/cache/other/off-plugin/1.0.0");
  skill(join(off, "skills"), "hidden", "Never offered");
  skill(join(configDir, "skills"), "own-skill", "The person's own skill");
  // a plugin whose manifest names its skills, one level deeper than skills/<name>/ (mattpocock-skills does this)
  const matt = join(configDir, "plugins/cache/mattpocock/mattpocock-skills/1.3.2");
  skill(join(matt, "skills/engineering"), "diagnosing-bugs", "Diagnosis loop for hard bugs");
  put(join(matt, ".claude-plugin/plugin.json"), JSON.stringify({ name: "mattpocock-skills", skills: ["./skills/engineering/diagnosing-bugs"] }));
  put(join(configDir, "plugins/installed_plugins.json"), JSON.stringify({ version: 2, plugins: {
    "compound-engineering@ce-market": [{ scope: "user", installPath: ce, version: "3.37.0" }],
    "off-plugin@other": [{ scope: "user", installPath: off, version: "1.0.0" }],
    "mattpocock-skills@mattpocock": [{ scope: "user", installPath: matt, version: "1.3.2" }],
  } }));
  put(join(configDir, "settings.json"), JSON.stringify({ enabledPlugins: { "compound-engineering@ce-market": true, "off-plugin@other": false, "mattpocock-skills@mattpocock": true } }));
}

function scan(env) {
  const r = Bun.spawnSync(["sh", "-c", SCAN, "scan", root], { env: { PATH: process.env.PATH, ...env } });
  return scanned(r.stdout.toString());
}

test("an enabled plugin's skills and commands are offered as /plugin:name, the person's own skills too", () => {
  const h = join(root, "h1");
  home(join(h, ".claude"));
  const names = scan({ HOME: h }).map((c) => c.name);
  expect(names).toContain("compound-engineering:ce-plan");
  expect(names).toContain("compound-engineering:lfg");
  expect(names).toContain("own-skill");
  expect(names).toContain("mattpocock-skills:diagnosing-bugs");
  expect(names).not.toContain("off-plugin:hidden");
  expect(scan({ HOME: h }).find((c) => c.name === "compound-engineering:ce-plan")?.about).toBe("Create structured plans");
});

test("Claude's own folder is read from CLAUDE_CONFIG_DIR when it is set", () => {
  const h = join(root, "h2");
  mkdirSync(h, { recursive: true });
  const cfg = join(root, "elsewhere/.claude-profile");
  home(cfg);
  const names = scan({ HOME: h, CLAUDE_CONFIG_DIR: cfg }).map((c) => c.name);
  expect(names).toContain("compound-engineering:ce-plan");
  expect(names).toContain("own-skill");
});
