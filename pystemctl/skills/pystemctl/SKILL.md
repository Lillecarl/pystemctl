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

`--wait` streams the command's output to stdout in text mode, then prints
the unit name to stderr; `--json` keeps a single payload on stdout.

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

`jobs` lists pystemctl's own jobs; other transient units (scopes, other
tools) stay hidden unless `--all-transient` is passed. Filter by tag
(newest job carrying every tag) or session. `wait` blocks until a unit
finishes or a log line matches. `tail` follows output until the unit stops
or a line matches.

The long-run loop: start tagged, wait in bounded chunks, then read the logs.
`run` prints the unit name; keep it for `logs` and `status`.

```sh
pystemctl run --tag deploy -- ./build.sh   # prints pystemctl-build-xxxx.service
pystemctl wait --tag deploy --timeout 300  # 0 done, 124 still running, else the unit's exit
pystemctl jobs --tag deploy                # same agent session
pystemctl logs --tag deploy -n 100        # unit name not needed
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

Target selector for `wait` / `tail` / `logs` / `status`: positional `UNIT`
or `--tag/-T TAG`. `logs` and `status` also take several units. A tag keeps
working after the job finishes and its unit unloads: tags ride along in the
journal, so the newest tagged entry resolves the name.

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

pystemctl log views show the program's output, not the manager's
Started/Stopped lifecycle lines; `pyjournalctl` shows everything, and
`--json` keeps every field.

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
- A finished job has two lifetimes. The manager unloads a successful unit
  within about a second unless it is still running, failed, or kept with
  `--remain-after-exit`; only the journal entries survive that, so `logs
  --tag` still reads a collected job's output but `wait` / `status` lose
  its exit status. `--no-collect` and `--tag` only skip that unloading,
  they do not pin the unit: `wait` promptly or use `--wait` when the exit
  code matters. (`wait` on a `--remain-after-exit` unit currently hangs;
  read its result with `status` or `logs` instead.)
- `stop` / `rm` name the owning session on stderr when the unit is another
  session's; `logs` fails on a name that never ran instead of printing
  nothing, and `status` says "could not be found" for those.
- Prefer `--json` plus `show -P` when scripting over `status` text.
- Lint and typecheck with `nix run --file . lint -- check` from the
  repository (`fix` autofixes what ruff can); `nix build` runs the same
  checks in the sandbox, so a red gate fails the build.
- Shell completion (bash, zsh, fish) completes subcommands, unit names
  and files, tags, sessions, slices, env keys, priorities, and property
  names from live state. A failed manager lookup completes nothing rather
  than erroring.
