# synapse-codemap

> Turn your repositories into a queryable **code map** inside your markdown vault.
> 100% local. Zero dependencies. One file.

`codemap` deconstructs your codebases (Python + TypeScript/TSX/JS/JSX) into one
markdown note per module — classes, exported functions, UI components, internal
dependencies — and writes them into your Obsidian vault (or any markdown
knowledge base). Your **code structure** and your **written decisions** finally
live in the same searchable place.

```
my-saas/backend/billing/*.py   →   vault/codemap/my-saas-code-billing.md
my-site/src/components/*.tsx   →   vault/codemap/my-site-code-components.md
```

Pair it with any semantic search over your vault and you can ask things like
*"where did I already implement a multi-provider adapter?"* — and get back the
**module that implements it** next to the **note that explains why**.

## Why this exists

Knowledge-graph extractors are powerful, but the popular ones send your code to
a cloud LLM to do the extraction. If your vault contains client data, that is a
non-starter — by architecture, not by policy.

The counter-intuitive lesson that produced this tool: **a lightweight extractor
is enough for the core value.** ~250 lines of Python stdlib (`ast` + regex)
capture what matters for cross-repo recall: modules, symbols, internal deps.
Nothing leaves your machine. Nothing to install except Python.

## Quickstart

```bash
# 1. Get the file (it's just one file)
curl -O https://raw.githubusercontent.com/thesok81/synapse-codemap/main/codemap.py

# 2. Configure your repos
cp codemap.config.example.json codemap.config.json
#    edit: vault output dir, projects root, repos with their source dirs

# 3. Generate
python codemap.py --all          # every configured repo
python codemap.py --repo my-saas # just one
python codemap.py --list         # show configured repos
```

Config schema (`codemap.config.json`, lives next to `codemap.py`):

```json
{
  "out": "/path/to/your/vault/codemap",
  "projects_root": "/path/to/your/projects",
  "repos": {
    "my-saas": {"dir": "my-saas-repo", "py": ["backend"], "ts": ["frontend/src"]},
    "my-cli":  {"path": "/absolute/path/elsewhere/my-cli", "py": ["."], "ts": []}
  }
}
```

- `dir` is relative to `projects_root`; use `path` for an absolute location.
- `py` / `ts` are the source folders to scan inside each repo.
- The repo slug becomes the note prefix: `<slug>-code-<module>.md`.

## Auto-regeneration (the part that keeps it alive)

A code map you must remember to regenerate goes stale in days — architecture
without workflow is dead architecture. So the workflow is built in:

```bash
python codemap.py --install-hooks      # post-commit hook in every configured repo
python codemap.py --uninstall-hooks    # clean removal (only touches our own hooks)
python codemap.py --check-fresh        # monitor: last commit vs notes, exit 1 if stale
```

The hook is **safe by design**: it never blocks a commit (`exit 0` always), it
never overwrites a pre-existing hook that isn't ours, and it only writes inside
`.git/hooks/` — never in your sources. `--check-fresh` gives you a one-command
health check you can schedule anywhere.

## Design guarantees

| Guarantee | How |
|---|---|
| 100% local | stdlib only — no network calls, no cloud, no telemetry |
| Zero dependencies | `python codemap.py` runs on a bare Python 3.10+ |
| Read-only on your repos | writes only to your vault dir + `.git/hooks/` |
| Regenerable namespace | notes are disposable artifacts — gitignore them in the vault |
| Bundle-proof | skips minified/huge JS, dot-dirs, `node_modules`, venvs, build output |

## Tests

```bash
python -m unittest test_codemap   # stdlib unittest, no test deps either
```

## Part of Synapse

`codemap` is the **cartographer** of [Synapse](https://github.com/thesok81) — a
local-first toolchain that treats your markdown vault as the single library
where curated notes and extracted code maps converge, with semantic search (
local embeddings) and an MCP server for AI assistants on top. The cartographer
is open source; the librarian is coming.

Built by **Telos Intelligence** — we build self-managed systems for ourselves
first, then for clients. This tool maps 8 production repositories daily on the
machine it was written on.

## License

MIT © 2026 Telos Intelligence LLC
