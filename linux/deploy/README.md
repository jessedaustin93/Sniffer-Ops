# SnifferOps Appliance — build, flash, and operate

The **appliance** is the headless SnifferOps node: `snifferops_linux.py` running
under a dedicated `snifferops` system user as a systemd service, no GTK. It
powers three SKUs — a prebuilt unit, a downloadable OS image, and a bundle
installer — all from this one body of work.

Desktop users want the GTK app instead: see [`../README.md`](../README.md) and
`../install.sh`.

## Layout

| Path | Purpose |
|---|---|
| `install-appliance.sh` | Headless installer: apt, `snifferops` user, `/opt/snifferops` + venv, systemd units. Idempotent. |
| `lib-install.sh` | Shared shell functions (also usable by the desktop installer). |
| `snifferops.service` | System service running the hub `--headless`. |
| `firstboot/snifferops-firstboot.service` + `.sh` | One-shot first-boot provisioning; self-disables. |
| `selftest.sh` | Health / assembly test — every unit runs it before it ships. |
| `../VERSION` | Semver source, stamped into the image name and `/etc/snifferops-version`. |
| `../../image/` | pi-gen config + custom stage that bakes all of the above into an `.img.xz`. |

## Install on an existing Debian/Bookworm box

```bash
sudo linux/deploy/install-appliance.sh
sudo systemctl start snifferops
linux/deploy/selftest.sh          # expect RESULT: OK
```

This installs to `/opt/snifferops`, creates the `snifferops` user (added to
`bluetooth`, `netdev`, `plugdev`, `dialout`), writes an RTL-SDR udev rule, and
enables the service. Data lives under **`/var/lib/snifferops`**
(`SNIFFEROPS_DATA_DIR`).

## Data, identity, and config

- `SNIFFEROPS_DATA_DIR` (default `~/.snifferops`, appliance `/var/lib/snifferops`)
  is the single knob that relocates identity, config, DB, and logs. Resolved in
  `linux/paths.py`, shared by the hub and the GUI.
- `node_id` is generated once and **stable across reboots**; the API on 8766
  reports it.
- `config.json` is written with defaults on first run
  (`wifi/bluetooth` on, `sdr`/`cellular` off until hardware is confirmed,
  `port: 8766`, `peers: []`, map home). Edit it to change scanners or peers —
  both the hub and GUI read the same file.

## First boot (flashed image)

`snifferops-firstboot.service` runs once and then disables itself
(sentinel `/var/lib/snifferops/.provisioned`). It:

1. Expands the root filesystem to fill the SD card.
2. Generates `node_id` + default `config.json` (same code as the hub).
3. Sets the hostname to `snifferops-<shortid>`.
4. Installs baked Wi-Fi credentials if present on the boot partition
   (`snifferops-wifi.nmconnection` or `wpa_supplicant.conf`).

The node scans **fully offline** — network is only needed for peer sync and
future signature-pack updates, not for local detection.

### Baking Wi-Fi (Phase 1)

Drop a NetworkManager keyfile named `snifferops-wifi.nmconnection` (or a
`wpa_supplicant.conf`) onto the boot partition after flashing; first boot moves
it into place and removes it from `/boot`.

## SD-card durability

Data is isolated on `/var/lib/snifferops` and SQLite runs in WAL mode, so a
power cut can't corrupt the OS — only the data partition is at risk, and WAL
recovers it. The installer (`apply_durability`) sets journald to
`Storage=volatile` so normal operation doesn't write the card.

Recommended additional hand-tuning on the SD image (not yet automated):

- root mount options `commit=30,noatime` (batch writes),
- boot partition `sync` (protect the FAT boot partition).

### Read-only root (stronger durability)

`deploy/durability/` implements a proper read-only root:

- On first boot, `setup-readonly-root.sh` carves a **data partition** from the
  card's free space (`snifferops-data`), moves `/var/lib/snifferops` onto it, and
  adds an fstab entry.
- It then enables the **Pi overlay filesystem** (`raspi-config enable_overlayfs`)
  so the OS root is read-only and all root writes go to RAM (discarded on
  reboot). Power loss can't corrupt the OS.
- The data partition is a separate mount that sits *over* the overlay, so the DB,
  `node_id`, and config **persist**; SQLite WAL recovers that partition.

The step is a one-shot `snifferops-hardening.service` that self-disables and is
**fail-safe** (any error leaves the node writable rather than broken). The image
build enables it (and stops root auto-expand so there's free space for the data
partition). Hand-installs stay writable by default; opt in with:

```bash
sudo systemctl enable snifferops-hardening.service && sudo reboot
```

Updating a read-only unit: `raspi-config nonint disable_overlayfs && reboot`,
apply changes, re-enable, reboot — or reflash. An A/B image is the eventual
stronger option.

**Status:** read-only-root is implemented but **validated only once the CI image
is flashed** (it repartitions + toggles the overlay, which needs a real flash to
exercise). Until then, the journald-volatile baseline applies and stable power
still matters.

**HW acceptance:** pull power 20× mid-scan; the OS should boot clean every time
and the DB should open without corruption.

## Validation status

Phase 1 was validated on a real **Pi Zero 2W** (Debian 13 / trixie, hand-install
via `install-appliance.sh`): the service runs headless under the `snifferops`
user with `ProtectSystem=strict` (no polkit relaxation needed), Wi-Fi **and**
onboard Bluetooth scanning work, the API answers on 8766 with a stable node id,
and the node survived repeated clean reboots with `selftest.sh` green each time.
Still outstanding: destructive power-loss testing, read-only-root/A-B, and the
CI-built pi-gen `.img.xz` (Bookworm target).

## Build the image (pi-gen)

CI (`.github/workflows/build-image.yml`) builds on a `v*` tag: it checks out
pi-gen (bookworm), drops in `image/config`, copies `image/stage-snifferops`,
builds with qemu/binfmt, then publishes `snifferops-os-<version>-arm64.img.xz`
plus a `.sha256` as a release asset.

Locally (needs Linux + loop devices + qemu):

```bash
git clone --branch bookworm https://github.com/RPi-Distro/pi-gen
cp image/config pi-gen/config
cp -r image/stage-snifferops pi-gen/stage-snifferops
export SNIFFEROPS_REPO="$PWD"
cd pi-gen && sudo -E ./build-docker.sh
```

## Update procedure

Read-only-root units: `mount -o remount,rw /`, apply changes (or
`pip install -U` inside `/opt/snifferops/venv`), `mount -o remount,ro /` — or
reflash a newer image. Verify a downloaded image with
`sha256sum -c snifferops-os-*.img.xz.sha256` before flashing.

## Provenance

Each image ships `/etc/snifferops-version` and a published SHA-256 (optionally
signed). Buyers can verify the image is unmodified — the same trust posture that
the later signed-signature-packs feature builds on.
