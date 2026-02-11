# Bluetooth Bitrate Manager

Bluetooth Bitrate Manager is a GTK4/Libadwaita desktop companion and CLI monitor that surfaces real-time codec stats for your Bluetooth audio devices on PipeWire. It also ships an opt-in builder that patches PipeWire's SBC plugin for higher bitpool values while keeping the original binary backed up.

## Screenshots

<p align="center">
  <img src="https://i.imgur.com/0M6h4jg.png" alt="Bluetooth Bitrate Manager GUI showing negotiated codec and bitrate" width="48%">
  <img src="https://i.imgur.com/wYLJubU.png" alt="bt-bitrate-monitor CLI output" width="48%">
  <br>
  <em>GTK4 app (left) and terminal monitor (right) showing real-time SBC parameters.</em>
</p>

## Table of contents
- [Highlights](#highlights)
- [Screenshots](#screenshots)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Build a high-bitrate SBC codec](#build-a-high-bitrate-sbc-codec)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

## Highlights
- Works with modern Linux desktops that use PipeWire/WirePlumber and BlueZ - no PulseAudio hacks required.
- Libadwaita interface auto-refreshes when devices connect, change codec, or negotiate a new bitrate.
- `bt-bitrate-monitor` CLI prints the same negotiated SBC parameters that the GUI shows, so you can script or SSH into remote machines.
- One-click "Build and Install High Bitrate Codec" action patches PipeWire's SBC plugin with your chosen bitpool and restores the original file on uninstall.
- `install.sh` bootstraps system packages across Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE, Alpine, Void, Solus, and Gentoo before installing to your user site.
- MIT licensed and versioned.

## Requirements
- Linux with PipeWire >= 0.3.x and WirePlumber (or another BlueZ-compatible session manager).
- Python 3.9 or newer.
- System GTK dependencies: PyGObject (`python3-gi`), GTK 4, and Libadwaita.
- PipeWire/BlueZ utilities: `pactl`, `pw-dump`, and `busctl`.
- Optional SBC rebuild: compiler toolchain (`git`, `meson`, `ninja`, `gcc`, `pkg-config`, `curl`).

## Installation

### Option 1 - Flatpak (recommended)

Install with one command:

```bash
flatpak install --user https://ezrakhuzadi.github.io/bluetooth-bitrate-manager/com.github.ezrakhuzadi.BluetoothBitrateManager.flatpakref
```

This automatically sets up the repository, GPG signing, Flathub runtime, and installs the app.

See [FLATPAK.md](FLATPAK.md) for alternative install methods and troubleshooting.

### Option 2 - Nix flake

The repository exposes a flake that packages the app similarly to the Arch package.

Install it into your profile:

```bash
nix profile install github:ezrakhuzadi/bluetooth-bitrate-manager#bluetooth-bitrate-manager
```

Or run it ad-hoc without installing:

```bash
nix run github:ezrakhuzadi/bluetooth-bitrate-manager
```

### Option 3 - Arch Linux (AUR)

Available as an AUR package maintained in this repository:

```bash
# with paru
paru -S bluetooth-bitrate-manager

# or with yay
yay -S bluetooth-bitrate-manager
```

> The package installs the GTK application, CLI tools, and optional SBC rebuild
> helper. It also ships the .desktop launcher and icon.

### Option 4 - install script (distro packages + user site)
The repository ships `install.sh`, which requests elevated privileges (root/sudo/doas), installs missing system dependencies, and performs a user-level pip install:

```bash
./install.sh
```

When `sudo` is used, the script keeps the sudo ticket alive during install. It then drops a `.desktop` launcher into `~/.local/share/applications/`.

After installation the following entry points are available on your PATH:
- `bluetooth-bitrate-gui` - start the GTK application.
- `bt-bitrate-monitor` - run the terminal monitor.

## Usage

### Launch the desktop app
Run `bluetooth-bitrate-gui` from a terminal or find "Bluetooth Bitrate Manager" in your desktop menu.

The app automatically:
- Lists currently connected Bluetooth audio sinks.
- Displays negotiated codec, bitrate, channel mode, block length, and sample rate.
- Refreshes live when devices connect/disconnect or the transport renegotiates.
- Shows a helper pane to configure high-bitpool SBC defaults and trigger the rebuild script.

### Run the terminal monitor
```bash
bt-bitrate-monitor
```

Optional flags:
- `-o/--once` - show the current state and exit (useful inside shell scripts).
- `-w/--watch` - refresh periodically to follow negotiations in real time.

Behind the scenes the monitor combines `pactl` data with SBC transport parsing from `bluetooth_bitrate_manager.bitrate_utils` to report the same numbers as the GUI.

## Build a high-bitrate SBC codec

From the GUI choose **Build and Install High Bitrate Codec**. The app runs `bluetooth_bitrate_manager/resources/build_high_bitpool.sh`, which:
1. Clones PipeWire at the host's current version.
2. Generates a SBC patch with your requested bitpool.
3. Builds `libspa-codec-bluez5-sbc.so` and installs it system-wide, backing up the stock binary alongside it.
4. Detects distro-specific install paths (including multiarch paths like `/usr/lib/aarch64-linux-gnu/spa-0.2/bluez5`).

How this interacts with desktop SBC-XQ options:
- Your desktop/WirePlumber still negotiates which codec is used (SBC vs SBC-XQ).
- The patch only changes SBC-XQ dual-channel bitpool defaults when SBC-XQ is already negotiated.
- If the active codec is plain SBC, this patch does not force a switch to SBC-XQ.

The script needs elevated privileges; the app detects `pkexec` or `sudo`, caches credentials, and keeps them alive for long builds. You can revert to the backed-up plugin at any time from the same dialog.

Prefer the CLI? Run the script directly:

```bash
# run as root, or with sudo/doas
bluetooth_bitrate_manager/resources/build_high_bitpool.sh
```

## Troubleshooting
- **No devices detected:** confirm PipeWire is running and that your Bluetooth headset shows up in `pactl list sinks`.
- **Missing GTK modules:** install `python3-gi`, `gtk4`, and `libadwaita` packages for your distribution.
- **SBC builder fails:** make sure build tools (`meson`, `ninja`, `gcc`, `pkg-config`, `curl`, `git`) are installed and that `/usr` is writable with elevated privileges.
- **Ubuntu/Debian SBC builder deps:** install `libdbus-1-dev` and `libglib2.0-dev` in addition to build tools.
- **Externally managed Python:** if pip refuses to install system-wide, use `pipx`, a virtual environment, or rerun the installer which retries with `--break-system-packages` when available.

## Development
Create a virtual environment or work inside your user site-packages:

```bash
python3 -m pip install --user --upgrade build
python3 -m pip install --user -e .

# Launch the GUI from source
python3 -m bluetooth_bitrate_manager.gui

# Exercise the monitor
python3 -m bluetooth_bitrate_manager.monitor --once
```

The codebase follows standard library formatting (88-100 character lines) and aims to keep functions pure where possible - please match the existing style. Run `./install.sh` on a dev box if you want to confirm the bootstrapper works across distributions.

See `CONTRIBUTING.md` for pull request guidelines and `RELEASE_NOTES.md` for the current changelog.

## License
MIT (c) Ezra
