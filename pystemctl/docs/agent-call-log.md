# Agent call log crawls

Queried the opencode SQLite database (`~/.local/share/opencode/opencode.db`,
table `part`) for real `pystemctl` invocations by agents, to find misuse
patterns worth fixing in code or teaching in `../skills/pystemctl/SKILL.md`.

## 2026-10-06: first crawl

- Watermark: `2026-10-06T15:37:44Z` (`time_created > 1791301064943`).
- Scope: 598 real invocations across 9 sessions (consumer sessions: aid,
  nixidae, solid-kubernetes, croshome).
- Findings that landed: chunk loop taught first with timeout sizing,
  wait-code-is-unit-code idiom, no-pipe `echo rc=$?`, `wait --grep` for quiet
  logs, `-o cat` for greps, stale remain-after-exit hang note deleted,
  comma-joined `-P`, `--dir` alias.
- Next crawl: only parts newer than the watermark above, to see whether the
  teaching stuck (especially: less `sleep`+poll, fewer exit files).
