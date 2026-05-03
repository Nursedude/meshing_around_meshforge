#!/bin/bash
# meshing_around_meshforge healthcheck — would CI be green right now?
#
# Mirrors CI's lint stack (black + isort + flake8). Born from the
# 2026-05-03 ecosystem audit which found this repo had been red 4
# days unnoticed.
#
# Usage:
#   scripts/healthcheck.sh                # lint + tests
#   scripts/healthcheck.sh --lint-only
#
# Exit: 0 ok / 1 lint / 2 tests / 3 setup

set -u
RUN_LINT=1
RUN_TESTS=1
for a in "$@"; do
    case "$a" in
        --lint-only) RUN_TESTS=0 ;;
        --tests-only) RUN_LINT=0 ;;
        --help|-h) head -15 "$0" | sed 's/^# \?//' ; exit 0 ;;
    esac
done

cd "$(dirname "$0")/.."
BLACK="${BLACK:-$HOME/.local/bin/black}"
ISORT="${ISORT:-$HOME/.local/bin/isort}"
FLAKE8="${FLAKE8:-$HOME/.local/bin/flake8}"
[ -x "$BLACK" ] || BLACK="$(command -v black)" || true
[ -x "$ISORT" ] || ISORT="$(command -v isort)" || true
[ -x "$FLAKE8" ] || FLAKE8="$(command -v flake8)" || true
# Module-mode fallback for tools installed via `pip install --user
# --break-system-packages` on Debian-flavored boxes (no shim in
# ~/.local/bin/). Use explicit if-blocks because bash &&/|| associate
# left-to-right with equal precedence — the one-liner form would
# reassign even when the binary exists.
if [ ! -x "$BLACK" ]  && python3 -c 'import black'  2>/dev/null; then BLACK="python3 -m black"; fi
if [ ! -x "$ISORT" ]  && python3 -c 'import isort'  2>/dev/null; then ISORT="python3 -m isort"; fi
if [ ! -x "$FLAKE8" ] && python3 -c 'import flake8' 2>/dev/null; then FLAKE8="python3 -m flake8"; fi

print_ok()   { printf "\033[1;32m✓\033[0m %s\n" "$1"; }
print_fail() { printf "\033[1;31m✗\033[0m %s\n" "$1"; }
print_step() { printf "\n\033[1;36m=== %s ===\033[0m\n" "$1"; }

RC=0
PATHS="meshing_around_clients tests"

# Helper: returns 0 if $1 names a runnable tool (file path OR module-mode
# command like "python3 -m black"). Tries `--version` to verify.
is_runnable() {
    [ -n "$1" ] || return 1
    eval "$1 --version" >/dev/null 2>&1
}

if [ "$RUN_LINT" -eq 1 ]; then
    print_step "Lint — black --check"
    if is_runnable "$BLACK" && eval "$BLACK --check $PATHS" ; then
        print_ok "black clean"
    else
        print_fail "black would reformat (run: $BLACK $PATHS)"
        RC=1
    fi

    print_step "Lint — isort --check-only"
    if is_runnable "$ISORT" && eval "$ISORT --check-only $PATHS" ; then
        print_ok "isort clean"
    else
        print_fail "isort would reorder (run: $ISORT $PATHS)"
        RC=1
    fi

    print_step "Lint — flake8"
    if is_runnable "$FLAKE8" && eval "$FLAKE8 $PATHS" ; then
        print_ok "flake8 clean"
    else
        print_fail "flake8 errors"
        RC=1
    fi
fi

if [ "$RUN_TESTS" -eq 1 ] && [ "$RC" -eq 0 ]; then
    print_step "Tests"
    if python3 -m pytest tests/ -q --tb=short --timeout=30 --timeout-method=thread 2>&1 | tail -30 ; then
        print_ok "Tests passed"
    else
        print_fail "Tests failed"
        RC=2
    fi
fi

print_step "Summary"
[ "$RC" -eq 0 ] && print_ok "All checks passed" || print_fail "Failures detected"
exit "$RC"
