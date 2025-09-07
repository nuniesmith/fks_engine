#!/usr/bin/env bash
set -euo pipefail

# sync_all.sh
# Comprehensive sync tool for this monorepo + its git submodules under shared/*.
# For each submodule:
#   1. git fetch origin
#   2. Show dirty status (if any)
#   3. Compute ahead/behind vs origin/<branch>
#   4. If only behind: fast-forward (merge --ff-only)
#   5. If diverged: rebase onto origin/<branch>
#   6. Push (setting upstream if needed)
# After all submodules processed, commit updated submodule pointers in the root repo
# and push the root if anything changed (or always when --force-root-push given).
#
# Usage:
#   ./scripts/sync_all.sh                # normal run (auto-commit pointer changes)
#   ./scripts/sync_all.sh --no-commit    # skip root commit of pointer updates
#   ./scripts/sync_all.sh --dry-run      # show what would happen (no writes/pushes)
#   ./scripts/sync_all.sh --force-root-push  # push root even if no pointer changes
#
# Exit codes:
#   0 success
#   10 rebase conflict occurred (user intervention required)
#   11 unexpected git failure

AUTO_COMMIT=1
DRY_RUN=0
FORCE_ROOT_PUSH=0
SUBMODULE_COMMIT_MSG="chore: sync submodule"
ROOT_COMMIT_MSG="chore: update submodule refs (sync_all)"

while [[ ${1:-} =~ ^- ]]; do
  case "$1" in
    --no-commit) AUTO_COMMIT=0 ; shift ;;
    --dry-run) DRY_RUN=1 ; shift ;;
    --force-root-push) FORCE_ROOT_PUSH=1 ; shift ;;
    --submodule-msg) SUBMODULE_COMMIT_MSG=${2:?need message}; shift 2 ;;
    --root-msg) ROOT_COMMIT_MSG=${2:?need message}; shift 2 ;;
    -h|--help)
      grep '^# ' "$0" | sed 's/^# //'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

info()  { printf "\033[1;34m[INFO]\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
err()   { printf "\033[1;31m[ERR ]\033[0m %s\n" "$*"; }
note()  { printf "\033[0;36m[....]\033[0m %s\n" "$*"; }

run() {
  if [ $DRY_RUN -eq 1 ]; then
    note "DRY: $*"
  else
    "$@"
  fi
}

ensure_submodules_initialized() {
  info "Initializing / updating submodules (recursive)"
  run git submodule update --init --recursive
}

get_submodule_paths() {
  git config --file .gitmodules --get-regexp path 2>/dev/null | awk '{print $2}'
}

process_submodule() {
  local path=$1
  echo
  info "Submodule: $path"
  if ! git -C "$path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    warn "Skipping (not a work tree)"
    return 0
  fi
  local branch
  branch=$(git -C "$path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)
  note "Branch: $branch"

  # Fetch
  if ! run git -C "$path" fetch --prune origin; then
    err "Fetch failed; continuing"
  fi

  # Determine upstream ref exists
  if ! git -C "$path" rev-parse --verify origin/$branch >/dev/null 2>&1; then
    warn "origin/$branch missing; attempting to push to create it"
  fi

  # Show dirty status
  local dirty
  dirty=$(git -C "$path" status --porcelain || true)
  if [ -n "$dirty" ]; then
    note "Local changes present; will attempt commit before sync"
    echo "$dirty"
    if [ $DRY_RUN -eq 0 ]; then
      run git -C "$path" add -A
      if ! git -C "$path" diff --cached --quiet; then
        run git -C "$path" commit -m "$SUBMODULE_COMMIT_MSG" || warn "Commit skipped"
      fi
    fi
  fi

  # Ahead/behind counts (HEAD...origin/main gives left=head side commits ahead of origin?)
  local counts ahead behind
  if git -C "$path" rev-parse --verify origin/$branch >/dev/null 2>&1; then
    counts=$(git -C "$path" rev-list --left-right --count HEAD...origin/$branch || echo '0 0')
    ahead=$(echo "$counts" | awk '{print $1}')
    behind=$(echo "$counts" | awk '{print $2}')
  else
    ahead=0; behind=0; counts="0 0";
  fi
  note "Ahead/Behind (HEAD...origin/$branch): $counts"

  # Decide action
  if [ "$ahead" = "0" ] && [ "$behind" != "0" ]; then
    note "Behind only -> fast-forward merge"
    if ! run git -C "$path" merge --ff-only origin/$branch; then
      err "Fast-forward failed; try manual rebase"; return 11
    fi
  elif [ "$ahead" != "0" ] && [ "$behind" != "0" ]; then
    note "Diverged -> rebase onto origin/$branch"
    if [ $DRY_RUN -eq 0 ]; then
      if ! git -C "$path" rebase origin/$branch; then
        err "Rebase conflict in $path"; return 10
      fi
    else
      note "DRY: would git rebase origin/$branch"
    fi
  else
    note "No sync action required (either up-to-date or ahead only)."
  fi

  # Push
  if git -C "$path" rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    note "Pushing to existing upstream"
    run git -C "$path" push || warn "Push failed"
  else
    note "Setting upstream and pushing"
    run git -C "$path" push -u origin "$branch" || warn "Initial push failed"
  fi
}

commit_root_pointer_updates() {
  # Detect pointer changes (modified submodule entries show as 'M path')
  if git status --porcelain | grep -E '^( M|M ) shared/' >/dev/null 2>&1; then
    if [ $AUTO_COMMIT -eq 1 ] && [ $DRY_RUN -eq 0 ]; then
      info "Committing root submodule pointer updates"
      run git add shared/*
      run git -c commit.gpgsign=false commit -m "$ROOT_COMMIT_MSG" || warn "Root commit skipped"
    else
      warn "Pointer updates detected but auto-commit disabled or DRY mode"
    fi
  else
    note "No root pointer changes"
  fi
}

push_root_repo() {
  local need_push=0
  if ! git diff --quiet HEAD; then need_push=1; fi
  if [ $FORCE_ROOT_PUSH -eq 1 ]; then need_push=1; fi
  if [ $need_push -eq 1 ]; then
    info "Pushing root repository"
    if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
      run git push || warn "Root push failed"
    else
      local b; b=$(git rev-parse --abbrev-ref HEAD)
      run git push -u origin "$b" || warn "Initial root push failed"
    fi
  else
    note "Root push not required"
  fi
}

main() {
  ensure_submodules_initialized
  local failures=0
  while read -r path; do
    [ -z "$path" ] && continue
    if ! process_submodule "$path"; then
      code=$?
      if [ $code -eq 10 ]; then
        err "Stopping due to rebase conflict in $path"; exit 10
      else
        failures=$((failures+1))
      fi
    fi
  done < <(get_submodule_paths)

  commit_root_pointer_updates
  push_root_repo

  if [ $failures -gt 0 ]; then
    warn "Completed with $failures non-critical failures"
  else
    info "Sync complete"
  fi
}

main "$@"
