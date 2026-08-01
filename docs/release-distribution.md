# Release Distribution

Pegasus releases are semantic-version distributions, not mutable branches.

1. Verify the reviewed commit locally.
2. Create one immutable annotated tag, such as `v1.2.3`, at that commit.
3. Build a source archive and SHA-256 checksum file from that tag.
4. Create a release manifest recording the tag, commit SHA, archive/checksum
   digests, and supported client targets.
5. Upload those three assets to the matching GitHub Release.

Use `python3 tools/build_release_manifest.py --tag vX.Y.Z --archive <archive>
--output <manifest>` after creating the archive. It rejects lightweight tags and
non-semantic tag names, but deliberately does not create tags or publish assets.

Never move or reuse a release tag. The repository does not implement remote
download or self-update: that would require authenticated release retrieval and
signature policy that are outside this portable local foundation.
