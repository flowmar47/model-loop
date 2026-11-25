#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="model-loop"
TARGETS=(
  "$HOME/.agents/skills"
  "$HOME/.cursor/skills"
  "$HOME/.claude/skills"
  "$HOME/.codex/skills"
  "$HOME/.gemini/skills"
  "$HOME/.pi/agent/skills"
)

usage() {
  cat <<EOF
Usage: $(basename "$0") [--list | --copy | --uninstall]

Install or manage the $SKILL_NAME skill across agent harnesses:
  (default)     Symlink $REPO_DIR into each target skills directory
  --list        Show installation status for each target without making changes
  --copy        Copy skill files instead of creating symlinks
  --uninstall   Remove $SKILL_NAME links or copies from each target
  -h, --help    Show this help
EOF
}

mode="link"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --list)
      mode="list"
      ;;
    --copy)
      mode="copy"
      ;;
    --uninstall)
      mode="uninstall"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [ "$mode" = "list" ]; then
  for dir in "${TARGETS[@]}"; do
    dest="$dir/$SKILL_NAME"
    if [ "$dest" = "$REPO_DIR" ]; then
      printf '%-45s source (repo)\n' "$dest"
    elif [ -L "$dest" ]; then
      target="$(readlink "$dest" || true)"
      if [ -e "$dest" ]; then
        printf '%-45s symlink -> %s\n' "$dest" "$target"
      else
        printf '%-45s dangling symlink -> %s\n' "$dest" "$target"
      fi
    elif [ -d "$dest" ]; then
      printf '%-45s directory (copy)\n' "$dest"
    elif [ -e "$dest" ]; then
      printf '%-45s file\n' "$dest"
    else
      printf '%-45s not installed\n' "$dest"
    fi
  done
  exit 0
fi

for dir in "${TARGETS[@]}"; do
  dest="$dir/$SKILL_NAME"
  if [ "$dest" = "$REPO_DIR" ]; then
    echo "skip $dest (source repository)"
    continue
  fi

  case "$mode" in
    link)
      mkdir -p "$dir"
      if [ -d "$dest" ] && [ ! -L "$dest" ]; then
        echo "error: $dest is an existing directory; remove it or run --uninstall first" >&2
        exit 1
      fi
      ln -sfn "$REPO_DIR" "$dest"
      echo "linked $dest -> $REPO_DIR"
      ;;
    copy)
      mkdir -p "$dir"
      rm -rf "$dest"
      mkdir -p "$dest"
      (cd "$REPO_DIR" && tar --exclude='.git' -cf - .) | (cd "$dest" && tar -xf -)
      echo "copied $REPO_DIR -> $dest"
      ;;
    uninstall)
      if [ -L "$dest" ] || [ -e "$dest" ]; then
        rm -rf "$dest"
        echo "removed $dest"
      else
        echo "absent $dest"
      fi
      ;;
  esac
done
