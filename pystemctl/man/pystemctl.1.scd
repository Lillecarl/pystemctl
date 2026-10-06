pystemctl(1)

# NAME

pystemctl - inspect and control systemd units, run ephemeral user units

# SYNOPSIS

*pystemctl* [_OPTION_]... _COMMAND_ [_ARGS_]...

*pystemctl run* [_OPTION_]... -- _COMMAND_...

# DESCRIPTION

*pystemctl* is a Python reimplementation of *systemctl*(1) and
*journalctl*(1), plus helpers for running commands as ephemeral (transient)
systemd units. It speaks to the managers over D-Bus and reads the journal
directly.

The default scope is the calling user's service manager. Pass *--system*
for the system manager. Most commands accept *--json* for machine-readable
output on stdout; human-oriented notes and warnings go to stderr.

Units started with *pystemctl run* get a generated name such as
*pystemctl-build-a3f9c1.service*, printed on stdout. Give the job one or
more *--tag* values to find it again after it finishes: tags are recorded
in the unit's environment and ride along in the journal, so *wait*,
*tail*, *logs*, and *status* resolve a tag to the newest matching job long
after the manager unloaded the unit itself.

*run* also records the caller's agent session on the job, taken from
*OPENCODE_SESSION_ID*, *OCAHUB_SESSION*, or *OC_SESSION* when present and
generated otherwise. *jobs* lists that session by default; *--session ID*
selects one and *--any-session* skips the filter. Acting on another
session's unit names the owning session on stderr.

# EPHEMERAL WORKFLOW

Start a tagged job, then poll it in bounded waits and read its logs. Keep
*--timeout* shorter than whatever will kill a hanging foreground command:
a wait that outlives its caller teaches nothing.

	pystemctl run --tag deploy -- ./build.sh++
	pystemctl wait --tag deploy --timeout 90; echo $?++
	pystemctl logs --tag deploy -n 100

When the result is the next thing and the wait fits in one foreground
command, *tail* does it in one call: it streams the output and exits with
the unit's code.

	pystemctl tail --tag deploy --timeout 300++
	pystemctl tail --tag deploy --timeout 300 >/dev/null

# COMMANDS

*run* [_OPTION_]... -- _COMMAND_...
	Start a command as an ephemeral unit. A bare run inherits the caller's
	full environment and working directory; *--setenv* wins over inherited
	values, *--clean* starts empty, and a *--profile* run keeps only its
	*inherit_env* patterns plus fixed *env*. *--wait* streams the output
	and prints the unit name to stderr; it has no timeout of its own, so
	bound long waits with *--runtime-max*, which terminates the unit on
	expiry. On 	return the unit name prints on stdout with a stderr hint
	naming the *tail*, *wait*, and *logs* calls that follow it. Secondary
	flags: *--unit NAME* instead of a generated name; *--description TEXT*
	to label it; *--working-directory* (*--dir*, *-D*) for where it runs;
	*--property* (*-P*) *NAME=VALUE* for unit settings; *--type*
	*simple*|*exec*|*oneshot*|*idle*; *--remain-after-exit* and
	*--no-collect* to keep the unit after it exits; *--collect* to unload
	it instead; *--replace* to take over an existing name; *--no-block*
	to return before the start job finishes; *--nice N* and *--slice
	SLICE* for scheduling; *--shell* to run through *sh -c*.

*jobs* [_OPTION_]...
	List pystemctl's own jobs, by tag or session. *--all* includes finished
	jobs; *--all-transient* also shows other tools' transient units.
	*--follow* emits a line whenever a job appears, changes, or goes away.

*wait* [_OPTION_]... (_--tag TAG_ | _UNIT_)
	Wait until a unit finishes or a log line matches, then report. *--grep
	PATTERN* returns early on a match and leaves the unit running; *-n*
	controls how many recent lines the match may come from. *--timeout
	SECONDS* gives up with exit 124. On a unit the manager already
	unloaded, *wait* reads the exit notice from the journal and still
	returns the code.

*tail* [_OPTION_]... (_--tag TAG_ | _UNIT_)
	Stream a unit's output until it stops or a line matches. By default the
	stream runs to the end of the unit and returns its exit status;
	*--until-exit* spells that out, *-f* streams with exit 0 instead, and
	*--grep PATTERN* returns 0 on a match and 1 without one. Works on
	collected units too, replaying what the journal holds.

*logs* [_OPTION_]... [_UNIT_ ...]
	Show journal entries: the program's output, not the manager's
	Started/Stopped lifecycle lines. Without *-n*, the last 10 lines
	replay. Accepts several units and *--tag*. Fails on a name that never
	ran instead of printing nothing. Never reports an exit code; use
	*wait*, *tail*, or *status* for that. Time, priority, boot, and output
	selection match journalctl (*--since*, *--until*, *-p*, *-b*, *-o*);
	see *pyjournalctl*(1).

*status* [_OPTION_]... [_UNIT_ ...]
	Show unit status with a recent log replay (*-n*, default 10;
	*--no-journal* skips it). A collected unit reports its recovered exit
	code where the result used to say it was gone.

*show* [_OPTION_]... [_UNIT_ ...]
	Dump unit properties. *-P NAME* prints only that property; repeat the
	flag or comma-join several names, systemctl-style.

*rm* _UNIT_...
	Stop and forget transient units. Removing a unit that already finished
	and was collected succeeds; removing a name that never ran fails, so a
	typo stays loud.

*list* (aliases *ls*, *units*) [_OPTION_]...
	List units, with *--all*, *--type*, *--state*, and *--ephemeral*
	filters.

*list-unit-files* [_OPTION_]...
	List installed unit files.

*start*, *stop*, *restart*, *reload* _UNIT_...
	Lifecycle actions, systemctl-style.

*is-active*, *is-failed*, *is-enabled* _UNIT_...
	Boolean checks with systemctl-compatible exit codes.

*enable*, *disable* _UNIT_...
	Enable or disable unit files.

*cat* _UNIT_...
	Show unit file contents, including drop-ins.

*daemon-reload*
	Reload unit files.

*profile* [_list_ | _show NAME_ | _path_]
	Inspect named run defaults from *profiles.toml*. CLI flags win over the
	profile.

# OPTIONS

Most options belong to one command; *run --help* and friends spell out
their own. The global ones:

*--user*
	Use the calling user's service manager (default).

*--system*
	Use the system service manager. Unit environments are visible on the
	system bus there: do not run secrets through env unless every local
	user may read them.

*--json*
	Emit JSON. Errors still go to stderr with a nonzero exit.

*-h*, *--help*
	Show the command's help and exit.

# EXIT STATUS

*0*
	Success: the unit exited 0, or a pattern matched.

_N_
	The unit's own non-zero exit status, from *run --wait*, *wait*, and
	*tail*.

*1*
	Failure without a unit exit code: signal death, manager-side results
	such as timeouts, *tail --grep* with no match, and commands that
	change state given a name that never ran.

*2*
	Command-line usage error.

*3*
	*status* on a unit that is inactive or collected, matching systemctl.

*4*
	A name that never ran, from commands that only read state (*status*,
	*logs*, *wait*, *tail*, *show*).

*124*
	A bounded *wait* or *tail* outlived its *--timeout*, the way
	*timeout*(1) reports it.

# FILES

*~/.config/pystemctl/profiles.toml*
	User run profiles. The site config directory holds system-wide ones;
	*pystemctl profile path* shows the exact search path.

# SEE ALSO

*pyjournalctl*(1), *systemctl*(1), *journalctl*(1)
