#!/usr/bin/env bash
# Manual, destructive acceptance-host emulator. Never run from automated tests.
set -euo pipefail

NODE_URL='https://nodejs.org/dist/v24.15.0/node-v24.15.0-linux-x64.tar.xz'
NODE_SHA256='472655581fb851559730c48763e0c9d3bc25975c59d518003fc0849d3e4ba0f6'
OPENCODE_URL='https://registry.npmjs.org/opencode-linux-x64/-/opencode-linux-x64-1.18.13.tgz'
OPENCODE_SRI='sha512-WVB/FwFdG4NLqEdraW264/q5WFiUDTwU4hDN/6qSLamsCV+SUurZhDOrmXC/5atNWZE1B6xEq5E8V60dAduKZg=='

usage() {
  cat <<'EOF'
Usage: sudo scripts/provision-v3-rc-host.sh --profile <cbm|engram|playwright|context7|final> --rc-archive <pegasus-harness-v3.1.0-rc.N.tar.gz> --confirm-recreate-user <mapped-user> [--browser <absolute-path>]

This is a test-only host emulator. It recreates exactly one mapped dedicated
account and installs fixed Node/OpenCode only inside that new account.
EOF
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

profile='' rc_archive='' recreate_user='' browser=''
while (($#)); do
  case "$1" in
    --profile) (($# >= 2)) || fail '--profile requires a profile name'; profile=$2; shift 2 ;;
    --rc-archive) (($# >= 2)) || fail '--rc-archive requires an RC archive path'; rc_archive=$2; shift 2 ;;
    --confirm-recreate-user) (($# >= 2)) || fail '--confirm-recreate-user requires the mapped user'; recreate_user=$2; shift 2 ;;
    --browser) (($# >= 2)) || fail '--browser requires an absolute browser path'; browser=$2; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[[ $(id -u) -eq 0 ]] || fail 'run as root only for a dedicated RC acceptance account'
case "$profile" in
  cbm) target_user='pegasus-harness' ;;
  engram) target_user='pegasus-harness-engram' ;;
  playwright) target_user='pegasus-harness-playwright' ;;
  context7) target_user='pegasus-harness-context7' ;;
  final) target_user='pegasus-harness-final' ;;
  *) fail 'unknown acceptance profile' ;;
esac
[[ $recreate_user == "$target_user" ]] || fail 'explicit recreation acknowledgement must name the mapped dedicated user'
[[ -n $rc_archive && -f $rc_archive && ! -L $rc_archive ]] || fail 'RC archive must be a regular file'
[[ $(basename -- "$rc_archive") =~ ^pegasus-harness-v3\.1\.0-rc\.[1-9][0-9]*\.tar\.gz$ ]] || fail 'only v3.1.0-rc.N archives are accepted'
target_home="/home/$target_user"
[[ $target_user != serg && $target_user != root && $target_home != /home/serg && $target_home != / ]] || fail 'serg and unsafe homes are protected'
if [[ -n $browser ]]; then
  [[ $browser == /* && -f $browser && ! -L $browser && -x $browser && $browser != "$target_home"/* ]] || fail 'browser must be an absolute regular executable outside the target home'
  while :; do
    [[ ! -L $browser && $(stat -c %U -- "$browser") == root && $((8#$(stat -c %a -- "$browser") & 022)) -eq 0 ]] || fail 'browser path must be root-owned and not group/world-writable'
    [[ $browser == / ]] && break
    browser=$(dirname -- "$browser")
  done
fi

# Refuse aliases or repurposed accounts before the one explicit destructive boundary.
if getent passwd -- "$target_user" >/dev/null; then
  [[ $(getent passwd -- "$target_user" | cut -d: -f6) == "$target_home" ]] || fail 'mapped account has an unsafe home'
  [[ -d $target_home && ! -L $target_home && $(stat -c %U -- "$target_home") == "$target_user" ]] || fail 'mapped home is unsafe'
  userdel -r -- "$target_user"
elif [[ -e $target_home ]]; then
  fail 'refuse an unowned existing mapped home'
fi
[[ ! -e $target_home ]] || fail 'recreated home still exists; stop instead of removing it manually'
useradd --create-home --home-dir "$target_home" --shell /bin/bash -- "$target_user"

sudo -n -u "$target_user" -H env "HOME=$target_home" bash -eu -c '
  base="$HOME/.local/pegasus-acceptance"
  mkdir -p "$base/node" "$base/opencode" "$HOME/.local/bin"
  curl --fail --location --proto =https --tlsv1.2 -o "$base/node.tar.xz" "'$NODE_URL'"
  printf "%s  %s\n" "'$NODE_SHA256'" "$base/node.tar.xz" | sha256sum -c -
  tar -xJf "$base/node.tar.xz" --strip-components=1 -C "$base/node"
  curl --fail --location --proto =https --tlsv1.2 -o "$base/opencode.tgz" "'$OPENCODE_URL'"
  test "$(openssl dgst -sha512 -binary "$base/opencode.tgz" | openssl base64 -A)" = "'${OPENCODE_SRI#sha512-}'"
  tar -xzf "$base/opencode.tgz" --strip-components=1 -C "$base/opencode"
  install -Dm0755 "$base/opencode/bin/opencode" "$HOME/.local/bin/opencode"
  "$base/node/bin/node" --version | grep -Fx "v24.15.0"
  "$HOME/.local/bin/opencode" --version | grep -Fx "1.18.13"
'
printf 'PROVISIONED profile=%s user=%s node=24.15.0 opencode=1.18.13\n' "$profile" "$target_user"
