# Versioning

Ethrox Detect uses one canonical version source: `version.json`.

The source-controlled release version uses Semantic Versioning:

```text
MAJOR.MINOR.PATCH
```

Prereleases use standard SemVer identifiers:

```text
0.2.0-alpha.1
0.2.0-beta.1
0.2.0-rc.1
```

The full runtime version also reports the release build number:

```text
0.2.0-rc.1+1
```

Git release tags stay clean SemVer tags, for example `v0.2.0-rc.1` or
`v0.2.0`. Build metadata is not included in normal Git tags.

## Meaning

- `MAJOR`: breaking architecture, protocol, storage, API, migration, or
  compatibility changes.
- `MINOR`: backward-compatible feature releases.
- `PATCH`: backward-compatible fixes, security updates, and release
  documentation corrections.
- `BUILD`: monotonically increasing distributable build number.

When `MINOR` increases, `PATCH` resets to zero. When `MAJOR` increases, both
`MINOR` and `PATCH` reset to zero. Every distributable build increments
`BUILD`.

## Commands

```bash
python3 tools/version.py show
python3 tools/version.py verify
python3 tools/version.py bump patch
python3 tools/version.py bump minor
python3 tools/version.py bump major
python3 tools/version.py bump build
python3 tools/version.py sync
```

The version tool validates `version.json`, refuses malformed SemVer, updates
derived version strings, reports checked files, and never commits or tags.

## Platform Mapping

| Platform | Version field |
|---|---|
| Linux product/API | `MAJOR.MINOR.PATCH[-PRERELEASE]` plus `BUILD` |
| Linux CLI | `Ethrox Detect VERSION (build BUILD)` |
| Windows ProductVersion | `MAJOR.MINOR.PATCH[-PRERELEASE]` |
| Windows FileVersion | `MAJOR.MINOR.PATCH.BUILD` without prerelease text |
| Android versionName | `MAJOR.MINOR.PATCH[-PRERELEASE]` |
| Android versionCode | monotonic code derived from release build policy |
| Appliance release file | `PRODUCT_NAME`, `VERSION`, `BUILD`, `FULL_VERSION`, `GIT_COMMIT`, `BUILD_DATE` |

## CI

CI must run:

```bash
python3 tools/version.py verify
python3 tools/check_branding.py
```

Release workflows should inject the Git commit SHA and UTC build date at build
time. GitHub run numbers are CI metadata and do not replace the official
source-controlled release `BUILD`.

Development builds may display an additional CI suffix such as
`0.2.0+build.47.ci.103`; official release metadata remains `0.2.0+47`.

## Artifacts

Release artifacts include the product slug, platform, version, and build:

```text
ethrox-detect-linux-0.2.0-rc.1-build.1.tar.gz
ethrox-detect-windows-0.2.0-rc.1-build.1.zip
ethrox-detect-android-0.2.0-rc.1-build.1.apk
ethrox-detect-os-0.2.0-rc.1-build.1.img.xz
```
