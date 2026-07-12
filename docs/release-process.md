# Release Process

Ethrox Detect releases are prepared from the active platform branches and are
validated before any stable tag is published.

## Prepare

1. Confirm the target version in `version.json`.
2. Run `python3 tools/version.py verify`.
3. Run `python3 tools/check_branding.py`.
4. Run platform tests and builds.
5. Generate artifacts using the `ethrox-detect-` prefix.
6. Generate SHA-256 checksums for every artifact.

## Tagging

Use clean SemVer tags:

```bash
git tag v0.2.0-rc.1
git push origin v0.2.0-rc.1
```

Do not create the stable `v0.2.0` tag until migration acceptance checks pass on
Linux, Windows, Android, watch companion, and appliance-image builds.

## Patch, Minor, Major, And Build Releases

```bash
python3 tools/version.py bump patch
python3 tools/version.py bump minor
python3 tools/version.py bump major
python3 tools/version.py bump build
python3 tools/version.py verify
```

Review the changed files, commit the version bump, build artifacts, and tag only
after validation succeeds.
