#!/usr/bin/env bash
# Start Pegasus v3's additive plan/apply flow from a verified release archive.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo ./install.sh --target-user <linux-user> [--client opencode|claude-code|all] [--confirm cbm|engram|playwright|context7] [--decline cbm|engram|playwright|context7]

Prints and applies an additive plan only for the named non-root Linux user.
--client defaults to all.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

target_user=''
client='all'
confirm=()
decline=()

while (($#)); do
  case "$1" in
    --target-user)
      (($# >= 2)) || fail '--target-user requires a Linux user name'
      target_user=$2
      shift 2
      ;;
    --client)
      (($# >= 2)) || fail '--client requires opencode, claude-code, or all'
      client=$2
      shift 2
      ;;
    --confirm|--decline)
      (($# >= 2)) || fail "$1 requires cbm, engram, playwright, or context7"
      case "$2" in cbm|engram|playwright|context7) ;; *) fail "unsupported dependency: $2" ;; esac
      if [[ $1 == --confirm ]]; then confirm+=(--confirm "$2"); else decline+=(--decline "$2"); fi
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unsupported argument: $1"
      ;;
  esac
done

[[ $(id -u) -eq 0 ]] || fail 'install.sh must be run as root with sudo from a verified, extracted release archive'
[[ -n $target_user ]] || fail '--target-user <linux-user> is required'
case "$client" in opencode|claude-code|all) ;; *) fail "unsupported client: $client" ;; esac

target_uid=$(id -u -- "$target_user" 2>/dev/null) || fail "target user does not exist: $target_user"
[[ $target_uid -ne 0 ]] || fail '--target-user must be a non-root Linux user'
target_home=$(getent passwd -- "$target_user" | cut -d: -f6)
[[ -n $target_home && -d $target_home ]] || fail "target user home is unavailable: $target_user"
command -v sudo >/dev/null 2>&1 || fail 'sudo is required to enter the target user account'
sudo -n -u "$target_user" -H true >/dev/null 2>&1 || fail "sudo cannot run commands as target user: $target_user"

python=''
reported_versions=()
for candidate in python3.13 python3.12 python3; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  version=$($candidate -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)
  [[ -n $version ]] && reported_versions+=("$candidate $version")
  if "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' >/dev/null 2>&1; then
    python=$(command -v "$candidate")
    break
  fi
done
[[ -n $python ]] || fail "Python 3.12+ is required before Pegasus can run; found: ${reported_versions[*]:-no Python 3 interpreter}"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
[[ -f $script_dir/bin/pegasus ]] || fail 'release archive is incomplete: bin/pegasus is missing'

sudo -n -u "$target_user" -H env "HOME=$target_home" "$python" "$script_dir/bin/pegasus" --home "$target_home" --target-user "$target_user" --client "$client" plan
exec sudo -n -u "$target_user" -H env "HOME=$target_home" "$python" "$script_dir/bin/pegasus" --home "$target_home" --target-user "$target_user" --client "$client" "${confirm[@]}" "${decline[@]}" apply
