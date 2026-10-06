---
name: pystemctl
description: Inspect and control systemd units and run ephemeral user units with pystemctl, query logs with pyjournalctl. Use when starting one-shot jobs, checking unit status, tailing output, waiting on units, listing jobs by tag or session, or working with pystemctl profiles.
---

# pystemctl

Python reimplementation of `systemctl` and `journalctl`, plus helpers for
ephemeral (transient) user units. Two entry points: `pystemctl` and
`pyjournalctl`.

## Scope

Default scope is `--user` (calling user's manager). Pass `--system` for the
system manager. Most commands accept `--json` for machine-readable output.

```sh
pystemctl list
pystemctl --system status nginx.service
pystemctl show -P ActiveState -P SubState myunit.service
```

## Run an ephemeral unit

`pystemctl run` starts a command as a transient unit. A bare run inherits
the caller's full environment and working directory, so it behaves like the
same command in the calling shell. Explicit `--setenv` wins over inherited
values; `--clean` starts empty instead. A `--profile` run keeps whitelist
semantics: only its `inherit_env` patterns plus fixed `env` carry over.

```sh
pystemctl run --tag deploy -- ./build.sh
pystemctl run --tag deploy --profile gpu -- ./train.py
pystemctl run --tag deploy --setenv KEY=VALUE --property MemoryMax=1G -- ./app
```

Everything else (`--unit`, `--slice`, `--nice`, `--shell`, `--replace`,
`--no-block`, …) is in `run --help`. Three rules matter:

- Tag every job you will wait on later: the tag resolves the unit after it
  finishes, when its generated name is already unloaded.
- A tag does not pin the unit. Successful units unload within about a
  second whether tagged or not; the tag rides along in the journal, so
  `wait` / `tail` / `logs --tag` keep working and the first two still
  report the exit code.
- `--wait` streams the command's output to stdout and prints the unit name
  to stderr; it has no timeout of its own, so bound it with `--runtime-max`,
  which terminates the unit on expiry.

## Unit lifecycle and inspection

systemctl parity throughout: `start` / `stop` / `restart` / `reload`,
`is-active` / `is-failed` / `is-enabled`, `enable` / `disable`, `cat`,
`daemon-reload`, `list`, `list-unit-files`, `show`. pystemctl-only:

```sh
pystemctl rm UNIT...              # stop and forget transient units; already-collected succeeds
pystemctl status myunit.service -n 20   # -n replays recent logs, --no-journal skips them
pystemctl show -P ActiveState,Result myunit.service   # comma-joins like systemctl -p
```

## Jobs, wait, tail

`jobs` lists pystemctl's own jobs by tag (newest carrying every tag) or
session. `wait` blocks until a unit finishes or a log line matches.
`tail` streams a unit's output until it stops and exits with its code;
`logs -n` peeks at past lines without waiting.

The default long-run loop: start tagged, then alternate bounded waits and
log reads. Size `--timeout` under your tool-call limit (about 90 second
chunks); a longer wait dies with the call and teaches nothing.

```sh
pystemctl run --tag deploy -- ./build.sh   # prints pystemctl-build-xxxx.service
pystemctl wait --tag deploy --timeout 90; echo rc=$?   # 0 done, 124 still running, else the unit's exit
pystemctl logs --tag deploy -n 100        # unit name not needed
```

`wait`'s exit code IS the unit's: no exit files needed. Read it with `; echo`
after the command, never through a pipe (`| tail` reports tail's code).
`--timeout 0` checks without waiting. Arriving late still works: `wait`
reads a collected unit's exit notice from the journal (0 clean, N the
unit's own failure, 1 for signals), and only a name that never ran fails
with 4.

One call instead, when the result is the next thing and the wait fits in one
tool call: `tail` resolves once, streams, and exits with the unit's code
(124 past `--timeout`).

```sh
pystemctl tail --tag deploy --timeout 300              # stream + exit code
pystemctl tail --tag deploy --timeout 300 >/dev/null   # only the exit code
```

`-f` streams with exit 0 instead, for pipelines. Watching a quiet log for
one line: `wait --tag deploy --grep READY --timeout 90` returns early on
the match instead of sleeping and re-reading. Piping `logs` into grep: add
`-o cat` for plain text without ANSI escapes. Judging when lines landed:
`-o compact` stamps each line, time alone (*HHMMSS*) for today's entries
and date plus time (*YYMMDDHHMMSS*) for older ones.

Sessions: `run` stamps the invoking agent session on the job. `jobs` lists
that session by default and falls back to every session when the scoped
answer is empty, saying so on stderr. `--any-session` skips the filter;
`--session ID` selects one. By tag, `wait` / `tail` / `logs` / `status`
resolve across sessions, newest match wins — and a tag keeps working after
the job's unit unloads, because tags ride along in the journal.

## Logs and journal

```sh
pystemctl logs myunit.service -n 50 -o cat
pyjournalctl --since '-1h' -p err --json
```

Time, priority, boot, and output flags match journalctl (`--since`,
`--until`, `-p`, `-b`, `-o`, `-f`; full list in `--help`). Without `-n`,
the last 10 lines replay. pystemctl log views show the program's output,
not the manager's Started/Stopped lines; `pyjournalctl` shows everything.

## Profiles

Named defaults in `profiles.toml` under the user config dir then the site
config dir (`pystemctl profile path` shows the search path). CLI flags win
over the profile.

```toml
[profiles.gpu]
description = "GPU batch job"
inherit_env = ["PATH", "CUDA_*"]
working_directory_mode = "caller"
tags = ["gpu"]
runtime_max = 3600.0
```

```sh
pystemctl profile list
pystemctl profile show gpu
```

## Notes

- With `--system`, unit environments are visible on the system bus. Do not
  run secrets through env there unless every local user may read them.
- A finished job has two lifetimes: the manager unloads a successful unit
  within about a second, and only the journal entries survive that. Tags
  ride along in the journal, so `wait` / `tail` / `logs --tag` keep working
  and `wait` / `tail` / `status` still report the exit code.
- `stop` / `rm` name the owning session on stderr when the unit is another
  session's; `logs` fails on a name that never ran instead of printing
  nothing.
- Prefer `--json` plus `show -P` when scripting over `status` text.
