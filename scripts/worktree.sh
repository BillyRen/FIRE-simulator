#!/usr/bin/env bash
# Isolated git worktree manager for concurrent Claude/dev sessions.
#
# Why: two sessions sharing one working directory corrupt each other —
# `git add` sweeps in the other session's uncommitted hunks, and a branch
# revert can silently delete the other session's work. A worktree gives each
# session its own working dir + index + HEAD (sharing the object DB), plus its
# own .next build dir and dev-server ports, eliminating the whole class of
# conflict. See memory/feedback-concurrent-sessions-shared-tree.md.
#
# Usage:
#   scripts/worktree.sh new <topic>     create ../FIRE_<topic> on branch feat/<topic>
#   scripts/worktree.sh list            list worktrees + assigned ports
#   scripts/worktree.sh dev <topic>     start backend+frontend for a worktree (nohup)
#   scripts/worktree.sh stop <topic>    stop that worktree's dev servers
#   scripts/worktree.sh rm <topic>      stop servers + remove the worktree
#
# Ports: each worktree gets index n (1..9); backend=8888+n, frontend=3000+n.
# The main checkout stays on 8888/3000.

set -euo pipefail

# Resolve the MAIN worktree (first line of `git worktree list`), so the script
# behaves identically whether invoked from main or from inside a worktree.
MAIN_ROOT="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
PARENT_DIR="$(dirname "$MAIN_ROOT")"

usage() { sed -n '2,22p' "$0"; exit 1; }

# Lowest index n in 1..9 whose ports (3000+n and 8888+n) are both free.
pick_index() {
  local n
  for n in 1 2 3 4 5 6 7 8 9; do
    if ! lsof -i ":$((3000 + n))" -sTCP:LISTEN >/dev/null 2>&1 \
       && ! lsof -i ":$((8888 + n))" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "$n"; return 0
    fi
  done
  echo "ERROR: no free port slot (1..9) found" >&2; return 1
}

wt_path() { echo "${PARENT_DIR}/FIRE_$1"; }

cmd_new() {
  local topic="${1:?topic required}" wt branch idx
  wt="$(wt_path "$topic")"; branch="feat/${topic}"
  [ -e "$wt" ] && { echo "ERROR: $wt already exists" >&2; exit 1; }

  idx="$(pick_index)"
  git -C "$MAIN_ROOT" worktree add -b "$branch" "$wt"

  # Isolate ports per worktree; record for dev/stop/list to read.
  printf 'IDX=%s\nBACKEND_PORT=%s\nFRONTEND_PORT=%s\n' \
    "$idx" "$((8888 + idx))" "$((3000 + idx))" > "$wt/.worktree-meta"

  # Reuse the main checkout's node_modules (gitignored, not checked out into
  # the worktree). Symlink is instant; if package.json diverges on this branch,
  # replace with a real `npm install` in the worktree.
  if [ -d "$MAIN_ROOT/frontend/node_modules" ]; then
    ln -s "$MAIN_ROOT/frontend/node_modules" "$wt/frontend/node_modules"
  fi

  echo
  echo "✅ worktree ready:"
  echo "   dir:      $wt"
  echo "   branch:   $branch"
  echo "   backend:  http://localhost:$((8888 + idx))"
  echo "   frontend: http://localhost:$((3000 + idx))"
  echo
  echo "   start servers:  scripts/worktree.sh dev $topic"
  echo "   open session:   cd $wt   (run your second Claude session HERE)"
}

cmd_list() {
  git worktree list | while read -r path rest; do
    if [ -f "$path/.worktree-meta" ]; then
      # shellcheck disable=SC1090
      . "$path/.worktree-meta"
      printf '%s  %s  [be:%s fe:%s]\n' "$path" "$rest" "$BACKEND_PORT" "$FRONTEND_PORT"
    else
      printf '%s  %s  [be:8888 fe:3000]\n' "$path" "$rest"
    fi
  done
}

cmd_dev() {
  local topic="${1:?topic required}" wt
  wt="$(wt_path "$topic")"
  [ -f "$wt/.worktree-meta" ] || { echo "ERROR: $wt/.worktree-meta missing (was it created with 'new'?)" >&2; exit 1; }
  # shellcheck disable=SC1091
  . "$wt/.worktree-meta"

  # nohup so the harness reaping a background task can't kill the servers
  # (lesson from the incident); separate .next per worktree avoids lock clashes.
  ( cd "$wt/backend" && nohup uvicorn main:app --port "$BACKEND_PORT" \
      > "/tmp/fire-${topic}-be.log" 2>&1 & echo $! > "/tmp/fire-${topic}-be.pid" )
  ( cd "$wt/frontend" && NEXT_PUBLIC_API_URL="http://localhost:$BACKEND_PORT" \
      nohup npx next dev -p "$FRONTEND_PORT" > "/tmp/fire-${topic}-fe.log" 2>&1 & echo $! > "/tmp/fire-${topic}-fe.pid" )

  echo "starting (detached)…"
  echo "  backend:  http://localhost:$BACKEND_PORT   (log: /tmp/fire-${topic}-be.log)"
  echo "  frontend: http://localhost:$FRONTEND_PORT  (log: /tmp/fire-${topic}-fe.log)"
}

cmd_stop() {
  local topic="${1:?topic required}" p
  for p in be fe; do
    if [ -f "/tmp/fire-${topic}-${p}.pid" ]; then
      kill "$(cat "/tmp/fire-${topic}-${p}.pid")" 2>/dev/null || true
      rm -f "/tmp/fire-${topic}-${p}.pid"
    fi
  done
  echo "stopped ${topic} servers"
}

cmd_rm() {
  local topic="${1:?topic required}" wt
  wt="$(wt_path "$topic")"
  cmd_stop "$topic" || true
  # Clear only our own scaffolding (always untracked, would block removal),
  # then do a NON-force remove so genuine uncommitted work still blocks it.
  rm -f "$wt/.worktree-meta"
  [ -L "$wt/frontend/node_modules" ] && rm -f "$wt/frontend/node_modules"
  if ! git -C "$MAIN_ROOT" worktree remove "$wt"; then
    echo "ERROR: worktree has uncommitted changes — commit/push first, or force:" >&2
    echo "       git worktree remove --force $wt" >&2
    exit 1
  fi
  echo "removed worktree $wt (branch feat/${topic} kept; delete with: git branch -D feat/${topic})"
}

case "${1:-}" in
  new)  shift; cmd_new "$@" ;;
  list) cmd_list ;;
  dev)  shift; cmd_dev "$@" ;;
  stop) shift; cmd_stop "$@" ;;
  rm)   shift; cmd_rm "$@" ;;
  *)    usage ;;
esac
