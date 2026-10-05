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
pystemctl run --wait -- sleep 5
pystemctl run --tag deploy --session abc -- ./build.sh
pystemctl run --profile gpu --nice 10 --slice batch.slice -- python train.py
pystemctl run --unit my-job --remain-after-exit --no-collect -- ./job.sh
pystemctl run --setenv KEY=VALUE --property MemoryMax=1G -- ./app
```

Key flags: `--unit NAME`, `--profile NAME`, `--description/-d`,
`--working-directory/-D`, `--setenv/-E KEY=VALUE` (repeatable),
`--clean` (empty environment), `--property/-P NAME=VALUE` (repeatable), `--type simple|exec|oneshot|idle`,
`--remain-after-exit`, `--collect` / `--no-collect`, `--replace`,
`--no-block`, `--wait`, `--runtime-max SECONDS`, `--nice N`, `--slice SLICE`,
`--shell` (run through `sh -c`), `--tag/-T TAG` (repeatable), `--session ID`.

Collect rule: explicit `--collect` / `--no-collect` wins. Otherwise a tagged
job is kept (so its exit status stays readable) and an untagged job is
collected once it stops.

## Unit lifecycle and inspection

```sh
pystemctl status myunit.service -n 20
pystemctl start|stop|restart|reload UNIT...
pystemctl rm UNIT...              # stop and forget transient units
pystemctl is-active|is-failed|is-enabled UNIT...
pystemctl enable|disable UNIT...
pystemctl cat UNIT...             # show unit file contents
pystemctl daemon-reload
pystemctl list --all --type service --state running
pystemctl list-unit-files --type service
```

`status` takes `-n/--lines N` for recent log replay and `--no-journal` to
skip logs.

## Jobs, wait, tail

`jobs` lists ephemeral jobs. Filter by tag (newest job carrying every tag) or
session. `wait` blocks until a unit finishes or a log line matches. `tail`
follows output until the unit stops or a line matches.

The long-run loop: start tagged, wait in bounded chunks, then read the logs.
`run` prints the unit name; keep it for `logs` and `status`.

```sh
pystemctl run --tag deploy -- ./build.sh   # prints pystemctl-build-xxxx.service
pystemctl wait --tag deploy --timeout 300  # repeat until the unit stops
pystemctl jobs --tag deploy                # same agent session
pystemctl logs pystemctl-build-xxxx.service -n 100
```

Sessions: `run` stamps the invoking agent session on the job. `jobs` lists
that session by default and falls back to every session when the scoped
answer is empty, saying so on stderr. `--any-session` skips the filter;
`--session ID` selects one. `wait` / `tail` by tag resolve across sessions,
newest match wins.

```sh
pystemctl jobs --tag deploy --any-session
pystemctl jobs --all --any-session
pystemctl jobs --follow
pystemctl wait myunit.service --timeout 30 --grep READY --lines 200
pystemctl wait --tag deploy --timeout 60
pystemctl tail myunit.service -n 200 -f
pystemctl tail --tag deploy --grep ERROR --until-exit
```

Target selector for `wait` / `tail`: positional `UNIT` or `--tag/-T TAG`
(mutually exclusive, one is required).

## Logs and journal

```sh
pystemctl logs myunit.service -n 50 --since '2026-01-01' -o cat
pystemctl logs myunit.service -f -p info -b
pyjournalctl -u myunit.service --user-unit other.service -n 100 -o short-precise
pyjournalctl --since '-1h' -p err --json
```

Shared log flags: `-n/--lines N`, `--since`, `--until`, `-p/--priority LEVEL`,
`-b/--boot [ID]`, `-o/--output short|short-iso|short-precise|short-full|cat|json|json-pretty|verbose`,
`-f/--follow`. Without `-n`, the last 10 lines replay (all of them with
`--since` and no `--follow`).

## Profiles

Named defaults in `profiles.toml` under the user config dir then the site
config dir (`pystemctl profile path` shows the search path). CLI flags win
over the profile.

```toml
[profiles.gpu]
description = "GPU batch job"
inherit_env = ["PATH", "CUDA_*", "HF_*"]
env = { PYTHONUNBUFFERED = "1" }
working_directory_mode = "caller"  # caller | static | as-is
# working_directory = "/srv/jobs"  # with mode static or as-is
unit_type = "oneshot"
tags = ["gpu"]
slice = "batch.slice"
nice = 10
runtime_max = 3600.0
remain_after_exit = true
collect = false
[profiles.gpu.properties]
MemoryMax = "8G"
```

```sh
pystemctl profile list
pystemctl profile show gpu
```

Profile completion for `--profile` comes from these files; argcomplete
resolves it at completion time.

## Notes

- Bare runs inherit the caller's environment; a missing var there means
  `--clean` was passed or a profile's `inherit_env` glob does not cover it.
- With `--system`, unit environments are visible on the system bus. Do not
  run secrets through env there unless every local user may read them.
- A collected unit loses its exit status. Keep `--no-collect` or a `--tag`
  when a later `wait` / `tail` / `jobs` lookup needs the result.
- Prefer `--json` plus `show -P` when scripting over `status` text.
- Shell completion (bash, zsh, fish) completes subcommands, unit names
  from the running manager, and profile names. A failed manager lookup
  completes nothing rather than erroring.
