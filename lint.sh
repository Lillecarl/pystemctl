#!/usr/bin/env bash
# pystemctl's lint entry point, wrapped by nix (see default.nix).
#
#   lint check [--root DIR] [PATH...]   ruff check + ruff format --check + pyrefly
#   lint fix [--root DIR] [PATH...]     ruff check --fix + ruff format
#
# With no PATHs the project's src and tests are checked. Everything runs
# with the working directory at the project root, so ruff and pyrefly find
# their settings in pyproject.toml by discovery -- the same settings apply
# whether this runs on a live checkout or on a sandbox copy.
#
# The pyrefly interpreter is the Python on PATH, which the wrapper fills
# with every project dependency, so third-party imports resolve without
# any stated search path.
set -euo pipefail

usage() {
    sed -n '2,/^set /p' "$0" | sed 's/^# \?//'
}

mode="check"
root=""
paths=()
while (($# > 0)); do
    case "$1" in
        check|fix)
            mode="$1"
            shift
            ;;
        --root)
            root="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while (($# > 0)); do
                paths+=("$1")
                shift
            done
            ;;
        -*)
            echo "lint: unknown flag $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            paths+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$root" ]]; then
    root="."
    # Tolerate running from the repository root: the package lives one
    # level down, and that is where the settings are.
    if [[ ! -f "$root/pyproject.toml" && -f "$root/pystemctl/pyproject.toml" ]]; then
        root="$root/pystemctl"
    fi
fi
if ((${#paths[@]} == 0)); then
    paths=(src tests)
fi
if [[ ! -f "$root/pyproject.toml" ]]; then
    echo "lint: no pyproject.toml under $root (pass --root DIR)" >&2
    exit 2
fi

cd "$root"
case "$mode" in
    check)
        ruff check "${paths[@]}"
        ruff format --check "${paths[@]}"
        pyrefly check "${paths[@]}"
        ;;
    fix)
        ruff check --fix "${paths[@]}"
        ruff format "${paths[@]}"
        ;;
esac
