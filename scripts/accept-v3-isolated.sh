#!/usr/bin/env bash
# Manual RC acceptance only. Automated tests may inspect this file but must never run it.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo scripts/accept-v3-isolated.sh --profile <cbm|engram|playwright|context7|final> --rc-archive <RC-archive.tar.gz> --rc-checksum <RC-archive.tar.gz.sha256> --release-manifest <RC-manifest.json> --staging-dir <new-absolute-directory> --evidence-file <new-absolute-file> --confirm-recreate-user <mapped-user>

This test-only acceptance orchestrator validates the RC before recreating its
single mapped account, provisions its fixed host, and applies the profile plan.
EOF
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

profile='' archive='' rc_checksum='' release_manifest='' staging_dir='' evidence_file='' recreate_user=''
while (($#)); do
  case "$1" in
    --profile) (($# >= 2)) || fail '--profile requires a profile name'; profile=$2; shift 2 ;;
    --rc-archive) (($# >= 2)) || fail '--rc-archive requires an RC archive path'; archive=$2; shift 2 ;;
    --rc-checksum) (($# >= 2)) || fail '--rc-checksum requires the RC checksum path'; rc_checksum=$2; shift 2 ;;
    --release-manifest) (($# >= 2)) || fail '--release-manifest requires the RC manifest path'; release_manifest=$2; shift 2 ;;
    --staging-dir) (($# >= 2)) || fail '--staging-dir requires a new absolute directory'; staging_dir=$2; shift 2 ;;
    --evidence-file) (($# >= 2)) || fail '--evidence-file requires a new absolute file'; evidence_file=$2; shift 2 ;;
    --confirm-recreate-user) (($# >= 2)) || fail '--confirm-recreate-user requires the mapped user'; recreate_user=$2; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[[ $(id -u) -eq 0 ]] || fail 'run this RC acceptance as root with sudo'
[[ -n $profile && -n $archive && -n $rc_checksum && -n $release_manifest && -n $staging_dir && -n $evidence_file && -n $recreate_user ]] || fail 'profile, RC archive/checksum/manifest, paths, and recreation acknowledgement are required'
[[ $staging_dir == /* && $evidence_file == /* ]] || fail 'staging directory and evidence file must be absolute paths'
[[ $staging_dir != / && $staging_dir != /home/* && ! -e $staging_dir && ! -e $evidence_file ]] || fail 'staging/evidence paths must be new and outside /home'
[[ -d $(dirname -- "$staging_dir") && -d $(dirname -- "$evidence_file") ]] || fail 'staging and evidence parents must already exist'
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
contract_tool="$script_dir/acceptance_v3_contract.py"
provisioner="$script_dir/provision-v3-rc-host.sh"
[[ -f $contract_tool && -x $provisioner ]] || fail 'acceptance laboratory scripts are incomplete'
archive=$(realpath -e -- "$archive") || fail 'RC archive does not exist'
rc_checksum=$(realpath -e -- "$rc_checksum") || fail 'RC checksum does not exist'
release_manifest=$(realpath -e -- "$release_manifest") || fail 'RC release manifest does not exist'

# This preflight must complete before the provisioner reaches its user recreation boundary.
preflight=$(python3 "$contract_tool" --profile "$profile" --rc-archive "$archive" --rc-checksum "$rc_checksum" --release-manifest "$release_manifest" --extract-dir "$staging_dir") || fail 'RC profile, checksum, manifest, or archive preflight failed'
target_user=$(PREFLIGHT="$preflight" python3 -c 'import json, os; print(json.loads(os.environ["PREFLIGHT"])["user"])')
confirm_csv=$(PREFLIGHT="$preflight" python3 -c 'import json, os; print(",".join(json.loads(os.environ["PREFLIGHT"])["confirm"]))')
decline_csv=$(PREFLIGHT="$preflight" python3 -c 'import json, os; print(",".join(json.loads(os.environ["PREFLIGHT"])["decline"]))')
release_root=$(PREFLIGHT="$preflight" python3 -c 'import json, os; print(json.loads(os.environ["PREFLIGHT"])["release_root"])')
release_identity=$(PREFLIGHT="$preflight" python3 -c 'import json, os; print(json.dumps(json.loads(os.environ["PREFLIGHT"])["release_identity"]))')
[[ $target_user != serg && $target_user != root && $recreate_user == "$target_user" ]] || fail 'serg and unsafe recreation acknowledgements are refused'
[[ -f $release_root/bin/pegasus ]] || fail 'validated RC archive lacks Pegasus'

snapshot=/tmp/pegasus-v3-serg-opencode.sha256
if [[ -d /home/serg/.config/opencode ]]; then
  find /home/serg/.config/opencode -xdev -type f -print0 | sort -z | xargs -0r sha256sum > "$snapshot"
else
  : > "$snapshot"
fi

"$provisioner" --profile "$profile" --rc-archive "$archive" --confirm-recreate-user "$recreate_user"
target_home="/home/$target_user"
host_path="$target_home/.local/pegasus-acceptance/node/bin:$target_home/.local/bin:/usr/local/bin:/usr/bin:/bin"
# The contract tool creates and validates every ancestor under /var/lib before
# copying. The target receives group read/execute permission, never write access.
release_root=$(python3 "$contract_tool" --prepare-handoff --release-root "$release_root" --target-user "$target_user") || fail 'verified RC handoff could not be secured'

sudo -n -u "$target_user" -H env "HOME=$target_home" "PATH=$host_path" python3 "$release_root/bin/pegasus" --release-root "$release_root" --home "$target_home" --target-user "$target_user" --client opencode plan
confirm_args=() decline_args=()
IFS=, read -r -a confirmed <<< "$confirm_csv"
IFS=, read -r -a declined <<< "$decline_csv"
for mcp in "${confirmed[@]}"; do [[ -n $mcp ]] && confirm_args+=(--confirm "$mcp"); done
for mcp in "${declined[@]}"; do [[ -n $mcp ]] && decline_args+=(--decline "$mcp"); done
apply_result="$staging_dir/apply-result.json"
sudo -n -u "$target_user" -H env "HOME=$target_home" "PATH=$host_path" python3 "$release_root/bin/pegasus" --release-root "$release_root" --release-identity "$release_identity" --home "$target_home" --target-user "$target_user" --client opencode "${confirm_args[@]}" "${decline_args[@]}" apply > "$apply_result"
sudo -n -u "$target_user" -H env "HOME=$target_home" "PATH=$host_path" python3 "$release_root/bin/pegasus" --release-root "$release_root" --home "$target_home" --target-user "$target_user" --client opencode validate
sudo -n -u "$target_user" -H env "HOME=$target_home" "PATH=$host_path" npm --prefix "$target_home/.config/opencode/notifier" ci --ignore-scripts

[[ -f $target_home/.local/share/pegasus-harness/journal-v3.json ]] || fail 'apply did not create an ownership journal'
[[ -z $(find "$target_home/.config/opencode" "$target_home/.local/share/pegasus-harness" -xdev ! -user "$target_user" -print -quit) ]] || fail 'acceptance artifacts are not owned by the mapped user'
if [[ -d /home/serg/.config/opencode ]]; then
  find /home/serg/.config/opencode -xdev -type f -print0 | sort -z | xargs -0r sha256sum | cmp -s "$snapshot" - || fail 'serg OpenCode snapshot changed'
else
  [[ ! -e /home/serg/.config/opencode ]] || fail 'serg OpenCode configuration was created'
fi

PROFILE="$profile" TARGET_USER="$target_user" TARGET_HOME="$target_home" CONFIRM="$confirm_csv" DECLINE="$decline_csv" APPLY_RESULT="$apply_result" RC_ARCHIVE="$archive" RC_CHECKSUM="$rc_checksum" RELEASE_MANIFEST="$release_manifest" EVIDENCE_FILE="$evidence_file" SNAPSHOT="$snapshot" python3 - <<'PY'
import hashlib, json, os
from pathlib import Path

keys = {"cbm": "codebase-memory-mcp", "engram": "engram", "playwright": "playwright", "context7": "context7"}
target = Path(os.environ["TARGET_HOME"])
confirmed = set(filter(None, os.environ["CONFIRM"].split(",")))
declined = set(filter(None, os.environ["DECLINE"].split(",")))
config = json.loads((target / ".config/opencode/opencode.json").read_text(encoding="utf-8"))
journal_path = target / ".local/share/pegasus-harness/journal-v3.json"
journal = json.loads(journal_path.read_text(encoding="utf-8"))
entries = journal.get("entries", [])
manifest = Path(os.environ["RELEASE_MANIFEST"])
manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
actual = set(config.get("mcp", {}))
expected = {keys[item] for item in confirmed}
if actual != expected or any((target / ".local/share/pegasus-harness/dependencies" / item).exists() for item in declined):
    raise SystemExit("selected MCP result or declined MCP no-orphan proof failed")
release = journal.get("release", {})
if (journal.get("schema") != "pegasus-harness-journal/v3" or journal.get("version") != "3.1.0"
        or release.get("version") != "3.1.0" or release.get("tag") != manifest_value["tag"]
        or not entries or any(item.get("ownership") != "owned" or not item.get("target") or not item.get("baseline_digest") for item in entries)):
    raise SystemExit("journal does not prove additive v3 ownership baselines")
apply = json.loads(Path(os.environ["APPLY_RESULT"]).read_text(encoding="utf-8"))
if (bool(confirmed - {"context7"}) != ("opencode-mcp" in apply.get("created", []))
        or ("context7" in confirmed) != ("context7-mcp" in apply.get("created", []))):
    raise SystemExit("apply result does not prove the selected MCP plan")
archive = Path(os.environ["RC_ARCHIVE"])
checksum = Path(os.environ["RC_CHECKSUM"])
evidence = {
    "schema": "pegasus-harness-rc-acceptance/v3",
    "status": "PASS",
    "profile": os.environ["PROFILE"],
    "target": {"user": os.environ["TARGET_USER"], "home": str(target)},
    "mcp_plan": {"confirmed": sorted(confirmed), "declined": sorted(declined), "selected_config_keys": sorted(actual), "declined_no_orphans": True},
    "archive": {"path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
    "rc_checksum": {"path": str(checksum), "sha256": hashlib.sha256(checksum.read_bytes()).hexdigest()},
    "release_manifest": {"path": str(manifest), "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()},
    "rc": {
        "tag": manifest_value["tag"],
        "archive_name": archive.name,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "checksum_sha256": hashlib.sha256(checksum.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "archive_root": json.loads(manifest.read_text(encoding="utf-8"))["archive_root"],
    },
    "journal": {"path": str(journal_path), "sha256": hashlib.sha256(journal_path.read_bytes()).hexdigest(), "entries": len(entries)},
    "ownership": {"target_user_only": True},
    "serg_snapshot_sha256": hashlib.sha256(Path(os.environ["SNAPSHOT"]).read_bytes()).hexdigest(),
}
Path(os.environ["EVIDENCE_FILE"]).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
PY

printf '%s\n' "PASS: profile $profile accepted; evidence recorded at $evidence_file. A failure requires a new commit/RC, never tag mutation."
