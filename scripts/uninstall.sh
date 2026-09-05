#!/usr/bin/env bash
# Remove every trace of this project from a Mac: the CLI, the MCP
# registrations in Claude Code and Codex, the Claude Code plugin, the skill
# leftovers from before v0.8.0, and the Claude Desktop extension. Safe to run
# when only some of them are present.
#
# Run from inside a clone and it also returns the working tree to the state
# git clone leaves it in, so the next install starts from nothing.
#
#   ./scripts/uninstall.sh                     # dry run, changes nothing
#   ./scripts/uninstall.sh --yes               # do it, keep password and .claude/
#   ./scripts/uninstall.sh --yes --password    # also delete ~/.config/asuswrt
#   ./scripts/uninstall.sh --yes --repo-all    # also delete the clone's .claude/
#
set -uo pipefail

APPLY=0
DROP_PASSWORD=0
DROP_CLAUDE_DIR=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes)      APPLY=1 ;;
    --password)    DROP_PASSWORD=1 ;;
    --repo-all)    DROP_CLAUDE_DIR=1 ;;
    -h|--help)     sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)             echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

FOUND=0
DONE=0

say()  { printf '%s\n' "$*"; }
hit()  { FOUND=$((FOUND+1)); printf '  %s\n' "$*"; }
ran()  { DONE=$((DONE+1)); }

# Run a command only when applying; otherwise just report it.
do_cmd() {
  if [ "$APPLY" -eq 1 ]; then
    if "$@" >/dev/null 2>&1; then ran; else say "      ! failed: $*"; fi
  fi
}

# Delete a path only when applying.
do_rm() {
  if [ "$APPLY" -eq 1 ]; then
    if rm -rf "$1" 2>/dev/null; then ran; else say "      ! could not remove $1"; fi
  fi
}

say "asuswrt cleanup"
[ "$APPLY" -eq 1 ] || say "(dry run — pass --yes to actually remove)"
say ""

# ---------------------------------------------------------------- the CLI ---
say "CLI and MCP binaries"
if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^asuswrt'; then
  hit "uv tool uninstall asuswrt"
  do_cmd uv tool uninstall asuswrt
fi
# uv normally takes these with it; catch a half-removed install too.
for f in asuswrt asuswrt-mcp asuswrt-probe; do
  if [ -e "$HOME/.local/bin/$f" ] || [ -L "$HOME/.local/bin/$f" ]; then
    hit "rm ~/.local/bin/$f"
    do_rm "$HOME/.local/bin/$f"
  fi
done
if [ -d "$HOME/.local/share/uv/tools/asuswrt" ]; then
  hit "rm -rf ~/.local/share/uv/tools/asuswrt"
  do_rm "$HOME/.local/share/uv/tools/asuswrt"
fi

# ------------------------------------------------------------- Claude Code ---
say ""
say "Claude Code"
# `claude mcp remove` only clears one scope at a time, so try all three: the
# server can be registered in ~/.claude.json (user), per project, or locally.
CC_REGISTERED=0
grep -q '"asuswrt"' "$HOME/.claude.json" 2>/dev/null && CC_REGISTERED=1
[ -f .mcp.json ] && grep -q '"asuswrt"' .mcp.json 2>/dev/null && CC_REGISTERED=1
if [ "$CC_REGISTERED" -eq 1 ]; then
  if command -v claude >/dev/null 2>&1; then
    hit "claude mcp remove asuswrt  (local, project and user scopes)"
    if [ "$APPLY" -eq 1 ]; then
      for scope in local project user; do
        claude mcp remove asuswrt --scope "$scope" >/dev/null 2>&1
      done
      if grep -q '"asuswrt"' "$HOME/.claude.json" 2>/dev/null; then
        say "      ! still present in ~/.claude.json — remove the asuswrt entry by hand"
      else
        ran
      fi
    fi
  else
    hit "asuswrt in ~/.claude.json — claude is not on PATH, remove the entry by hand"
  fi
fi
if command -v claude >/dev/null 2>&1; then
  if claude plugin list 2>/dev/null | grep -q asuswrt; then
    hit "claude plugin uninstall asuswrt@asuswrt"
    do_cmd claude plugin uninstall asuswrt@asuswrt
  fi
  if claude plugin marketplace list 2>/dev/null | grep -q asuswrt; then
    hit "claude plugin marketplace remove asuswrt"
    do_cmd claude plugin marketplace remove asuswrt
  fi
fi
# The skill folder and its symlink; the skill no longer exists as of v0.8.0.
for p in "$HOME/.claude/skills/asuswrt" "$HOME/.agents/skills/asuswrt"; do
  if [ -e "$p" ] || [ -L "$p" ]; then
    hit "rm -rf ${p/#$HOME/\~}"
    do_rm "$p"
  fi
done

# ------------------------------------------------------------------ Codex ---
say ""
say "Codex and ChatGPT"
if grep -q '^\[mcp_servers\.asuswrt\]' "$HOME/.codex/config.toml" 2>/dev/null; then
  if command -v codex >/dev/null 2>&1; then
    hit "codex mcp remove asuswrt"
    if [ "$APPLY" -eq 1 ]; then
      codex mcp remove asuswrt >/dev/null 2>&1
      if grep -q '^\[mcp_servers\.asuswrt\]' "$HOME/.codex/config.toml" 2>/dev/null; then
        say "      ! still in ~/.codex/config.toml — delete the [mcp_servers.asuswrt] block by hand"
      else
        ran
      fi
    fi
  else
    hit "[mcp_servers.asuswrt] in ~/.codex/config.toml — codex is not on PATH, delete the block by hand"
  fi
fi
# ChatGPT (the app and the web) keeps connectors server-side, so nothing local
# to delete. Remove it there under Settings -> Connectors if you added it.

# --------------------------------------------------------- Claude Desktop ---
say ""
say "Claude Desktop"
DESKTOP="$HOME/Library/Application Support/Claude"
if grep -q '"asuswrt"' "$DESKTOP/claude_desktop_config.json" 2>/dev/null; then
  hit "\"asuswrt\" in claude_desktop_config.json — remove that entry by hand"
fi
while IFS= read -r p; do
  [ -n "$p" ] || continue
  hit "rm -rf $p"
  do_rm "$p"
done < <(find "$DESKTOP" -maxdepth 3 -iname '*asus*' 2>/dev/null)
# A downloaded bundle, if it is still sitting where the README's curl left it.
for p in "$HOME/asuswrt.mcpb" "$HOME/Downloads/asuswrt.mcpb"; do
  if [ -e "$p" ]; then
    hit "rm ${p/#$HOME/\~}"
    do_rm "$p"
  fi
done

# --------------------------------------------------------------- password ---
say ""
say "Saved password"
if [ -d "$HOME/.config/asuswrt" ]; then
  if [ "$DROP_PASSWORD" -eq 1 ]; then
    hit "rm -rf ~/.config/asuswrt"
    do_rm "$HOME/.config/asuswrt"
  else
    say "  ~/.config/asuswrt kept (pass --password to delete it too)"
  fi
fi

# ------------------------------------------------------------- repo state ---
# Only touches the working directory when it really is a clone of this repo,
# so running this from anywhere else can never delete the wrong thing.
say ""
say "Repository working tree"
REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO" ]; then
  say "  (not inside a git repository — skipped)"
elif [ ! -d "$REPO/src/asuswrt" ] || ! grep -q '^name = "asuswrt"' "$REPO/pyproject.toml" 2>/dev/null; then
  say "  (not a clone of this repo — skipped)"
elif [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then
  say "  ! uncommitted changes to tracked files — skipping, commit or stash first:"
  git -C "$REPO" status --short --untracked-files=no | sed 's/^/      /'
else
  # -e .claude keeps your local Claude Code settings (sandbox exclusions and
  # the like), which a fresh clone would not have anyway. --repo-all drops it.
  CLEAN_ARGS=(-xd)
  [ "$DROP_CLAUDE_DIR" -eq 1 ] || CLEAN_ARGS+=(-e .claude)
  # Never let git clean delete the script while bash is still reading it.
  # Once this file is committed git clean skips it anyway; this covers the
  # case where it was dropped into the tree untracked.
  SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  case "$SELF" in
    "$REPO"/*)
      SELF_REL="${SELF#$REPO/}"
      git -C "$REPO" ls-files --error-unmatch "$SELF_REL" >/dev/null 2>&1 || CLEAN_ARGS+=(-e "$SELF_REL")
      ;;
  esac
  REPO_ITEMS=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    REPO_ITEMS=$((REPO_ITEMS+1))
    hit "${line/Would remove /rm -rf }"
  done < <(git -C "$REPO" clean "${CLEAN_ARGS[@]}" -n)
  if [ "$APPLY" -eq 1 ] && [ "$REPO_ITEMS" -gt 0 ]; then
    if git -C "$REPO" clean "${CLEAN_ARGS[@]}" -f >/dev/null 2>&1; then
      DONE=$((DONE+REPO_ITEMS))
    else
      say "      ! git clean failed"
    fi
  fi
  [ "$DROP_CLAUDE_DIR" -eq 1 ] || say "  .claude/ kept (pass --repo-all to delete it too)"
fi

# ----------------------------------------------------------------- report ---
say ""
if [ "$FOUND" -eq 0 ]; then
  say "Nothing found. This Mac is already clean."
elif [ "$APPLY" -eq 1 ]; then
  say "Removed $DONE of $FOUND items."
  say "Verify: command -v asuswrt        (should print nothing)"
  say "        git status --ignored -s   (should print nothing)"
else
  say "$FOUND items would be removed. Re-run with --yes."
fi
