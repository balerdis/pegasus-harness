#!/usr/bin/env bash
# Manual RC acceptance only. Automated tests may inspect this file but must never run it.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo scripts/accept-v3-isolated.sh --rc-tag v3.1.0-rc.N --archive <RC-archive.tar.gz> --release-manifest <RC-manifest.json> --staging-dir <new-absolute-directory> --evidence-file <new-absolute-file> --target-user pegasus-harness --confirm-clean-home

Accepts one explicit v3.1.0 RC archive against the already existing, empty
/home/pegasus-harness account. It never creates, deletes, resets, or reuses users.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

rc_tag=''
archive=''
release_manifest=''
staging_dir=''
evidence_file=''
target_user=''
confirmed_clean_home=false

while (($#)); do
  case "$1" in
    --rc-tag) (($# >= 2)) || fail '--rc-tag requires v3.1.0-rc.N'; rc_tag=$2; shift 2 ;;
    --archive) (($# >= 2)) || fail '--archive requires an RC archive path'; archive=$2; shift 2 ;;
    --release-manifest) (($# >= 2)) || fail '--release-manifest requires the RC manifest path'; release_manifest=$2; shift 2 ;;
    --staging-dir) (($# >= 2)) || fail '--staging-dir requires a new absolute directory'; staging_dir=$2; shift 2 ;;
    --evidence-file) (($# >= 2)) || fail '--evidence-file requires a new absolute file'; evidence_file=$2; shift 2 ;;
    --target-user) (($# >= 2)) || fail '--target-user requires pegasus-harness'; target_user=$2; shift 2 ;;
    --confirm-clean-home) confirmed_clean_home=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[[ $(id -u) -eq 0 ]] || fail 'run this RC acceptance as root with sudo'
[[ $rc_tag =~ ^v3\.1\.0-rc\.[1-9][0-9]*$ ]] || fail '--rc-tag must be v3.1.0-rc.N; final tags are refused'
[[ -n $archive && -n $release_manifest && -n $staging_dir && -n $evidence_file ]] || fail 'archive, manifest, staging directory, and evidence file are all required'
[[ $target_user == pegasus-harness ]] || fail 'acceptance is restricted to the existing pegasus-harness user'
[[ $confirmed_clean_home == true ]] || fail '--confirm-clean-home is required; this script refuses an implicit home choice'
archive=$(realpath -e -- "$archive") || fail 'RC archive does not exist'
release_manifest=$(realpath -e -- "$release_manifest") || fail 'RC release manifest does not exist'
[[ -f $archive && ! -L $archive && -f $release_manifest && ! -L $release_manifest ]] || fail 'archive and release manifest must be regular files'
[[ $staging_dir == /* && $evidence_file == /* ]] || fail 'staging directory and evidence file must be absolute paths'
[[ ! -e $staging_dir && ! -e $evidence_file ]] || fail 'staging directory and evidence file must not already exist'
[[ $staging_dir != / && $staging_dir != /home/* ]] || fail 'staging directory must not be /home or an existing user home'
[[ -d $(dirname -- "$staging_dir") && -d $(dirname -- "$evidence_file") ]] || fail 'staging and evidence parents must already exist'

target_home=/home/pegasus-harness
target_uid=$(id -u -- "$target_user" 2>/dev/null) || fail 'the dedicated user must already exist'
[[ $(getent passwd -- "$target_user" | cut -d: -f6) == $target_home ]] || fail 'pegasus-harness must own /home/pegasus-harness exactly'
[[ -d $target_home && ! -L $target_home ]] || fail 'the isolated home must be a real directory'
[[ $(stat -c %u -- "$target_home") == $target_uid ]] || fail 'the isolated home has the wrong owner'
[[ -z $(find "$target_home" -mindepth 1 -maxdepth 1 -print -quit) ]] || fail 'the isolated home is not clean; stop instead of deleting or reusing it'
command -v sudo >/dev/null 2>&1 || fail 'sudo is required to enter the isolated user account'
sudo -n -u "$target_user" -H sh -c 'command -v opencode >/dev/null' || fail 'OpenCode must be installed in the isolated user environment first'
sudo -n -u "$target_user" -H sh -c 'command -v npm >/dev/null' || fail 'npm must be installed in the isolated user environment first'

snapshot=/tmp/pegasus-v3-serg-opencode.sha256
if [[ -d /home/serg/.config/opencode ]]; then
  find /home/serg/.config/opencode -xdev -type f -print0 | sort -z | xargs -0r sha256sum > "$snapshot"
else
  : > "$snapshot"
fi

RC_TAG=$rc_tag ARCHIVE=$archive RELEASE_MANIFEST=$release_manifest STAGING_DIR=$staging_dir EVIDENCE_FILE=$evidence_file python3 - <<'PY'
import hashlib
import json
import os
import re
import tarfile
from pathlib import Path

tag = os.environ["RC_TAG"]
archive = Path(os.environ["ARCHIVE"])
manifest_path = Path(os.environ["RELEASE_MANIFEST"])
staging = Path(os.environ["STAGING_DIR"])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
expected_name = f"pegasus-harness-{tag}.tar.gz"
root = f"pegasus-harness-{tag}"
if (manifest.get("schema") != "pegasus-harness-release/v3" or manifest.get("tag") != tag
        or manifest.get("archive_root") != root or archive.name != expected_name
        or manifest.get("assets") != [{"name": archive.name, "sha256": archive_digest}]):
    raise SystemExit("RC tag, archive name, or release manifest mismatch")
curated = manifest.get("curated_dependencies")
evidence = manifest.get("archive_evidence")
if not isinstance(curated, list) or len(curated) != 1 or curated[0].get("id") != "cbm" or not isinstance(evidence, list):
    raise SystemExit("release manifest lacks curated CBM or archive evidence")
required = {"manifests/release-contract.json", "manifests/artifact-catalog.json", "manifests/cbm-linux-x64-provenance.json", curated[0].get("path")}
if {item.get("path") for item in evidence} != required:
    raise SystemExit("release manifest evidence is incomplete")
with tarfile.open(archive, "r:gz") as contents:
    members = contents.getmembers()
    if any(member.issym() or member.islnk() or not (member.isfile() or member.isdir()) for member in members):
        raise SystemExit("RC archive contains unsafe member types")
    names = {member.name for member in members}
    if any(not name.startswith(root + "/") for name in names):
        raise SystemExit("RC archive has an unexpected top-level path")
    for item in evidence:
        member = contents.getmember(f"{root}/{item['path']}")
        payload = contents.extractfile(member)
        if not member.isfile() or payload is None or hashlib.sha256(payload.read()).hexdigest() != item.get("sha256"):
            raise SystemExit(f"archive evidence mismatch: {item['path']}")
    provenance_member = contents.getmember(f"{root}/manifests/cbm-linux-x64-provenance.json")
    provenance = json.loads(contents.extractfile(provenance_member).read())
    contract_member = contents.getmember(f"{root}/manifests/release-contract.json")
    contract = json.loads(contents.extractfile(contract_member).read())
    cbm_contract = next((item for item in contract.get("dependencies", []) if item.get("id") == "cbm"), {})
    cbm_member = contents.getmember(f"{root}/{curated[0]['path']}")
    cbm_payload = contents.extractfile(cbm_member)
    if (not cbm_member.isfile() or cbm_payload is None
            or hashlib.sha256(cbm_payload.read()).hexdigest() != curated[0].get("sha256")
            or curated[0].get("sha256") != provenance.get("artifact_sha256")
            or curated[0].get("provenance") != "manifests/cbm-linux-x64-provenance.json"
            or cbm_contract.get("source_url") != f"release-bundle:{curated[0]['path']}"):
        raise SystemExit("curated CBM digest/provenance mismatch")
    staging.mkdir(mode=0o700)
    contents.extractall(staging, members=members, filter="data")
print(root)
PY

release_root=$staging_dir/pegasus-harness-$rc_tag
[[ -x $release_root/install.sh && -f $release_root/bin/pegasus ]] || fail 'validated RC archive lacks its installer path'
python3 "$release_root/bin/pegasus" --target-user "$target_user" --client opencode plan
"$release_root/install.sh" --target-user "$target_user" --client opencode \
  --decline cbm --decline engram --decline playwright --decline context7
sudo -n -u "$target_user" -H npm --prefix "$target_home/.config/opencode/notifier" ci --ignore-scripts
python3 "$release_root/bin/pegasus" --target-user "$target_user" --client opencode validate

[[ -f $target_home/.local/share/pegasus-harness/journal-v3.json ]] || fail 'apply did not create an ownership journal'
[[ -z $(find "$target_home/.config/opencode" "$target_home/.local/share/pegasus-harness" -xdev ! -user "$target_user" -print -quit) ]] || fail 'acceptance artifacts are not owned by pegasus-harness'
if [[ -d /home/serg/.config/opencode ]]; then
  find /home/serg/.config/opencode -xdev -type f -print0 | sort -z | xargs -0r sha256sum | cmp -s "$snapshot" - || fail 'serg OpenCode snapshot changed'
else
  [[ ! -e /home/serg/.config/opencode ]] || fail 'serg OpenCode configuration was created'
fi

RC_TAG=$rc_tag ARCHIVE=$archive RELEASE_MANIFEST=$release_manifest EVIDENCE_FILE=$evidence_file TARGET_HOME=$target_home SNAPSHOT=$snapshot python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

target = Path(os.environ["TARGET_HOME"])
journal = json.loads((target / ".local/share/pegasus-harness/journal-v3.json").read_text(encoding="utf-8"))
entries = journal.get("entries", [])
if not entries or any(item.get("release") != "3.1.0" or not item.get("baseline_digest") for item in entries):
    raise SystemExit("journal does not prove additive v3.1 ownership baselines")
keys = [(item.get("target"), item.get("key")) for item in entries]
if len(keys) != len(set(keys)):
    raise SystemExit("journal has duplicate ownership entries")
archive = Path(os.environ["ARCHIVE"])
manifest = Path(os.environ["RELEASE_MANIFEST"])
evidence = {
    "schema": "pegasus-harness-rc-acceptance/v3",
    "status": "PASS",
    "rc_tag": os.environ["RC_TAG"],
    "archive": {"path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
    "release_manifest": {"path": str(manifest), "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()},
    "journal": {"path": str(target / ".local/share/pegasus-harness/journal-v3.json"), "sha256": hashlib.sha256((target / ".local/share/pegasus-harness/journal-v3.json").read_bytes()).hexdigest(), "entries": len(entries)},
    "serg_snapshot_sha256": hashlib.sha256(Path(os.environ["SNAPSHOT"]).read_bytes()).hexdigest(),
    "additive_no_overwrite": {"clean_home_confirmed": True, "duplicate_ownership_entries": False},
}
Path(os.environ["EVIDENCE_FILE"]).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
PY

printf '%s\n' "PASS: RC archive accepted; evidence recorded at $evidence_file. Create v3.1.0 only after reviewing this evidence."
