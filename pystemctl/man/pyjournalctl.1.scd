pyjournalctl(1)

# NAME

pyjournalctl - query the systemd journal

# SYNOPSIS

*pyjournalctl* [_OPTION_]... [*--user-unit* _UNIT_]...

# DESCRIPTION

*pyjournalctl* is a Python reimplementation of *journalctl*(1). It reads
the journal directly and shows everything, including the manager's
lifecycle lines that *pystemctl logs* filters out.

# OPTIONS

*-u*, *--unit UNIT*
	Show entries for a system unit. Repeat for several.

*--user-unit UNIT*
	Show entries for a user unit. Repeat for several.

*-n*, *--lines N*
	How many recent lines to read.

*--since SINCE*, *--until UNTIL*
	Only entries in the time range.

*-p*, *--priority LEVEL*
	Only entries at or above the priority.

*-b*, *--boot* [_ID_]
	Only entries from a boot.

*-o*, *--output short*|*short-iso*|*short-precise*|*short-full*|*compact*|*cat*|*json*|*json-pretty*|*verbose*
	Output format. *cat* prints plain message text, good for piping into
	*grep*(1). *compact* stamps each line numerically, time alone
	(*HHMMSS*) for today's entries and date plus time (*YYMMDDHHMMSS*)
	for older ones.

*-f*, *--follow*
	Keep printing new lines as they arrive.

*--json*
	Emit JSON. Equivalent to *-o json* with the full entry kept.

*--no-pager*
	Accepted for journalctl compatibility; output never pages.

# EXAMPLES

	pyjournalctl --user-unit myunit.service -n 100 -o short-precise++
	pyjournalctl --since '-1h' -p err --json

# SEE ALSO

*pystemctl*(1), *journalctl*(1)
