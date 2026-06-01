# Learner Code Review — 2026-05-31

GPT-5.4 (Beef API) 3-round writer-critic review of `hermes_learner.py` and shell scripts.
12 critical bugs found, all fixed. 30,581 total review tokens.

## Bugs Found & Fixed

### generate_insight source parameter bug (CRITICAL)
`generate_insight()` checks `source == "AI HOT"` / `"GitHub 热榜"` / `"Arxiv"` to branch,
but all three fetchers called it with `{"title": ..., "summary": ...}` — no `source` field.
Result: insights were always generic defaults. Fix: pass the full finding dict.

### save_proposals dedup format mismatch (CRITICAL)
Dedup parser looked for `- **action** │ benefit: ...` (single-line format with `│`),
but proposals are actually written as two lines:
```
- **action**
  - 📈 收益: ...
```
Result: dedup never matched anything, duplicate proposals generated daily.
Fix: changed to URL-based dedup (normalize URL to scheme+netloc+path).

### Arxiv retry root unbound (CRITICAL)
`root = ET.fromstring(...)` inside try/except; if all 3 attempts hit `break` without success,
`for entry in root.findall(...)` throws `UnboundLocalError`.
Fix: initialize `root = None`, check `if root is None: continue`.

### seen per-source load/save race (HIGH)
Each fetch function called `load_seen()` and `save_seen()` independently.
If cron overlapped or ran concurrently, later runs could overwrite earlier seen state.
Fix: centralized in `main()` — load once, pass to all sources, save once at end.

### Non-atomic file writes (HIGH)
`open(path, "w")` for JSON/YAML/Markdown — interrupt mid-write produces corrupt files.
Fix: write to `.tmp` file, then `os.replace(tmp, final)`.

### Shell year hardcoding (HIGH)
`absorb_learnings.sh` and `list_pending_proposals.sh` used `2026-*.md` glob pattern.
Cross-year boundary (2027+) would silently miss all files.
Fix: changed to `20??-??-??.md`.

### Shell nullglob missing (HIGH)
`for f in "$PROPOSALS_DIR"/*.md` in empty dir iterates over literal `*.md` string.
Fix: added `shopt -s nullglob` and `set -euo pipefail`.

### format_report exception swallowing (HIGH)
`except Exception: pass` on health dashboard reading — directory not found, permissions,
or parse errors silently lost. Fix: added `logger.warning(...)` and `os.path.isdir()` check.

### Proposal state machine inconsistency (MEDIUM)
`deferred` status appeared in health dashboard but not in state flow docs or operations.
Fix: added `pending → deferred` transition and operational instructions.

### Git score bonus uncapped (MEDIUM)
Star bonus and agent/MCP bonus added after `score = min(score, 10)`, could exceed 10.
Fix: moved `score = min(score, 10)` to after all bonuses.

### score_item unused parameters (MEDIUM)
Signature had `source_name, category` that were never used.
Fix: removed, simplified to `score_item(title, summary)`.

### Other fixes
- `.env` file read without context manager → added `with open(..., encoding="utf-8")`
- `format_report` missing table header for source status → added header row
- `save_proposals` slug could be empty → added `or "proposal"` fallback
