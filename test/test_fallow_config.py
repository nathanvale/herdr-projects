"""Fallow's config against the copies bin/sync-shared writes, and the pinned Fallow tool package.

A generated copy (lib/COPIES) carries a whole shared module into a mod. Fallow's config names each copy so
duplication and complexity are reported once, at the source in lib/ or core/. These tests keep that list equal
to what sync-shared writes, so a new or dropped copy cannot silently skew the report.
"""
import importlib.machinery
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def written_copies():
    """Every path bin/sync-shared writes: mods/<mod>/<name> for each lib/COPIES row."""
    loader = importlib.machinery.SourceFileLoader("sync_shared", str(ROOT / "bin/sync-shared"))
    spec = importlib.util.spec_from_loader("sync_shared", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return {f"mods/{mod}/{name}" for name, mods in module.copies().items() for mod in mods}


def expand(pattern):
    """A literal path, or one with a single {a,b,...} group of literal names; anything else is refused."""
    if re.search(r"[*?\[\]!]", pattern) or pattern.count("{") > 1:
        raise AssertionError(f"copy pattern must be literal with at most one {{a,b}} group: {pattern}")
    match = re.fullmatch(r"([^{}]*)\{([^{}]+)\}([^{}]*)", pattern)
    if not match:
        if "{" in pattern or "}" in pattern:
            raise AssertionError(f"malformed copy pattern: {pattern}")
        return [pattern]
    head, names, tail = match.groups()
    return [head + name + tail for name in names.split(",")]


def expanded(patterns):
    paths = [path for pattern in patterns for path in expand(pattern)]
    if len(paths) != len(set(paths)):
        raise AssertionError("a copy is listed twice")
    return set(paths)


class FallowConfig(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / ".fallowrc.json").read_text())
        self.copies = written_copies()

    def test_every_copy_list_equals_what_sync_shared_writes(self):
        overrides = [o for o in self.config["overrides"] if o.get("rules") == {"unused-exports": "off", "unused-types": "off"}]
        self.assertEqual(len(overrides), 1, "one override turns off export findings in the generated copies")
        lists = {
            "duplicates.ignore": self.config["duplicates"]["ignore"],
            "health.ignore": self.config["health"]["ignore"],
            "overrides[copies].files": overrides[0]["files"],
        }
        for where, patterns in lists.items():
            with self.subTest(where=where):
                self.assertEqual(expanded(patterns), self.copies)

    def test_tool_package_pins_one_exact_fallow(self):
        package = json.loads((ROOT / "tools/fallow/package.json").read_text())
        version = package["devDependencies"]["fallow"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$", "pin Fallow exactly; the lockfile and docs name this version")
        self.assertIn(f'"fallow@{version}"', (ROOT / "tools/fallow/bun.lock").read_text())


if __name__ == "__main__":
    unittest.main()
