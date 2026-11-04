# Coding standards

## Regression coverage

- Write meaningful regressions with changes. Follow [AGENTS.md](AGENTS.md)
  for local verification; CI runs the tests.
- Add browser cases to their topic's `layout-*.test.ts` file, using
  `test/layout.ts` for setup. Split files exceeding about 20 seconds.
- Core protocol fakes test boundaries. They do not replace native-agent
  or device acceptance.

## Plugin compatibility

- Treat client and server `definePlugin` and `Registry` slots as public
  contracts used by personal plugins.
- Keep existing names working where possible.
- When changing a contract, update [docs/plugins.md](docs/plugins.md) and
  identify the compatibility change in the completion summary.
