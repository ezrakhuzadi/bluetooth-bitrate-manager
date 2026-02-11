# Flatpak Installation

## Quick Install (Recommended)

**One command that actually works:**
```bash
flatpak install --user https://ezrakhuzadi.github.io/bluetooth-bitrate-manager/com.github.ezrakhuzadi.BluetoothBitrateManager.flatpakref
```

This automatically:
- Adds the app repository with GPG verification
- Adds Flathub (for the GNOME runtime) if you don't already have it
- Installs the app and all dependencies

### Run the app:
```bash
flatpak run com.github.ezrakhuzadi.BluetoothBitrateManager
```

### Update the app:
```bash
flatpak update com.github.ezrakhuzadi.BluetoothBitrateManager
```

---

## Alternative Install Methods

### Option 1: Direct Bundle (Offline Install)

Download and install a `.flatpak` bundle:
- **x86_64**: https://ezrakhuzadi.github.io/bluetooth-bitrate-manager/com.github.ezrakhuzadi.BluetoothBitrateManager-x86_64.flatpak
- **aarch64**: https://ezrakhuzadi.github.io/bluetooth-bitrate-manager/com.github.ezrakhuzadi.BluetoothBitrateManager-aarch64.flatpak

```bash
flatpak install --user https://ezrakhuzadi.github.io/bluetooth-bitrate-manager/com.github.ezrakhuzadi.BluetoothBitrateManager-x86_64.flatpak
```

### Option 2: Manual Repository Setup (Advanced)

If you prefer to add the remote manually:

```bash
# Add Flathub first (if not already present in your user installation)
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

# Add the app repository
flatpak remote-add --user --if-not-exists bluetooth-bitrate https://ezrakhuzadi.github.io/bluetooth-bitrate-manager/bluetooth-bitrate.flatpakrepo

# Install the app
flatpak install --user bluetooth-bitrate com.github.ezrakhuzadi.BluetoothBitrateManager
```

**Important:** The manual method requires Flathub to be added to the **same installation** (user or system) you're installing the app to. If you use `--user` for the app, add Flathub with `--user` too.

## Build Requirements for SBC Rebuild

The Flatpak can rebuild SBC codecs, but requires build tools on your **host system**:

```bash
sudo pacman -S git meson ninja gcc pkgconf pipewire
```

Ubuntu/Debian equivalent:

```bash
sudo apt-get install -y git meson ninja-build gcc pkg-config curl libdbus-1-dev libglib2.0-dev
```

The build script will run on your actual system (outside the sandbox) when you click "Build and Install High Bitrate Codec" in the app.

## Permissions

The Flatpak has these permissions:
- Wayland/X11 display access
- PipeWire/PulseAudio audio
- Bluetooth D-Bus access
- Home directory access (for copying build scripts)
- Host command execution (for SBC rebuild via flatpak-spawn)
- Bluetooth hardware device access

## Uninstall

```bash
flatpak uninstall com.github.ezrakhuzadi.BluetoothBitrateManager
flatpak remote-delete bluetooth-bitrate
```

## Maintainer signing setup

GitHub Actions signs the repository metadata, so a GPG key must be configured.

### Generate signing key (one-time)

```bash
gpg --quick-gen-key "Bluetooth Bitrate Manager (Flatpak) <noreply@example.com>" rsa4096 sign 2y
gpg --list-secret-keys --keyid-format=long  # note the key ID
```

### Export secrets for CI

```bash
# Private key for FLATPAK_GPG_PRIVATE_KEY secret
gpg --export-secret-keys --armor YOURKEYID > FLATPAK_GPG_PRIVATE_KEY.asc

# Public key published to users
gpg --export --armor YOURKEYID > bluetooth-bitrate.gpg
```

Add repository secrets:
- `FLATPAK_GPG_PRIVATE_KEY`: contents of `FLATPAK_GPG_PRIVATE_KEY.asc`
- `FLATPAK_GPG_PASSPHRASE`: optional passphrase used when generating the key

Publish `bluetooth-bitrate.gpg` alongside the Flatpak repo (it is uploaded automatically by CI).

When the key is rotated, update both secrets and the published `.gpg` file, then re-run the workflow.
