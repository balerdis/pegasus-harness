#!/usr/bin/env bash
# Start Pegasus v3's additive plan/apply flow from a verified release archive.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install.sh [--client opencode|claude-code|all] [--confirm cbm|engram|playwright|context7] [--decline cbm|engram|playwright|context7]

Runs the additive plan and apply flow for the current non-root Linux user.
Each missing optional MCP requires exactly one --confirm or --decline decision.
--client defaults to all.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

client='all'
confirm=()
decline=()

while (($#)); do
  case "$1" in
    --target-user)
      fail '--target-user is no longer supported; run install.sh directly from the Linux account that will use Pegasus'
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

[[ $(id -u) -ne 0 ]] || fail 'install.sh must not run as root; open a shell as the Linux user who will use Pegasus and run it directly'
case "$client" in opencode|claude-code|all) ;; *) fail "unsupported client: $client" ;; esac

current_user=$(id -un)
current_home=${HOME:-}
[[ -n $current_home && -d $current_home && -O $current_home ]] || fail 'HOME must be an existing directory owned by the current Linux user'

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
[[ -f $script_dir/tools/validate_snapshot.py ]] || fail 'release archive is incomplete: tools/validate_snapshot.py is missing'

"$python" "$script_dir/tools/validate_snapshot.py"
"$python" "$script_dir/bin/pegasus" --release-root "$script_dir" --home "$current_home" --target-user "$current_user" --client "$client" plan
exec "$python" "$script_dir/bin/pegasus" --release-root "$script_dir" --home "$current_home" --target-user "$current_user" --client "$client" "${confirm[@]}" "${decline[@]}" apply
