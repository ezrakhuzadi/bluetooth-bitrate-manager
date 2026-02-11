#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(
  cd -- "$(dirname "${BASH_SOURCE[0]}")"
  pwd
)"
PROJECT_ROOT="$SCRIPT_DIR"

echo "Bluetooth Bitrate Manager installer"
echo "-----------------------------------"

if ! command -v sudo >/dev/null 2>&1; then
  echo "Error: sudo is required to install dependencies." >&2
  exit 1
fi

echo "Requesting administrator privileges up front..."
sudo -v

# Keep sudo timestamp fresh while the script runs.
while true; do
  sudo -v
  sleep 60
done &
KEEPALIVE_PID=$!
trap 'kill "$KEEPALIVE_PID"' EXIT

detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  elif command -v zypper >/dev/null 2>&1; then
    echo "zypper"
  elif command -v emerge >/dev/null 2>&1; then
    echo "emerge"
  else
    echo "unknown"
  fi
}

PKG_MANAGER=$(detect_pkg_manager)
echo "Detected package manager: ${PKG_MANAGER}"

install_packages() {
  local manager=$1
  shift
  local packages=("$@")

  if [ "${#packages[@]}" -eq 0 ]; then
    return
  fi

  case "$manager" in
    apt)
      sudo apt-get update
      sudo apt-get install -y "${packages[@]}"
      ;;
    dnf)
      sudo dnf install -y "${packages[@]}"
      ;;
    pacman)
      sudo pacman -Sy --needed "${packages[@]}"
      ;;
    zypper)
      sudo zypper refresh
      sudo zypper install -y "${packages[@]}"
      ;;
    emerge)
      sudo emerge --update --newuse "${packages[@]}"
      ;;
    *)
      echo "Warning: unsupported package manager. Please install dependencies manually:"
      printf '  %s\n' "${packages[@]}"
      ;;
  esac
}

case "$PKG_MANAGER" in
  apt)
    install_packages apt \
      python3 python3-pip python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
      pipewire wireplumber meson ninja-build gcc pkg-config curl git \
      libdbus-1-dev libglib2.0-dev
    ;;
  dnf)
    install_packages dnf \
      python3 python3-pip python3-gobject gtk4 libadwaita \
      pipewire pipewire-alsa pipewire-pulseaudio wireplumber \
      meson ninja-build gcc make pkgconf curl git dbus-devel glib2-devel
    ;;
  pacman)
    install_packages pacman \
      python python-pip python-gobject gtk4 libadwaita \
      pipewire wireplumber meson ninja gcc pkgconf curl git
    ;;
  zypper)
    install_packages zypper \
      python311 python311-pip python311-gobject gtk4 libadwaita \
      pipewire wireplumber meson ninja gcc pkg-config curl git dbus-1-devel glib2-devel
    ;;
  emerge)
    install_packages emerge \
      dev-lang/python dev-python/pip dev-python/pygobject dev-libs/glib \
      gui-libs/gtk gui-libs/libadwaita media-video/pipewire media-video/wireplumber \
      dev-util/meson dev-util/ninja sys-devel/gcc virtual/pkgconfig net-misc/curl dev-vcs/git
    ;;
  *)
    echo "Continuing without automatic dependency installation."
    ;;
esac

echo "Installing Bluetooth Bitrate Manager (user site-packages)..."
python3 -m pip install --user --upgrade pip >/dev/null 2>&1 || true
if python3 -m pip install --user --force-reinstall "$PROJECT_ROOT"; then
  :
else
  if python3 -m pip help install 2>/dev/null | grep -q -- '--break-system-packages'; then
    echo "Detected externally managed Python environment; retrying with --break-system-packages."
    python3 -m pip install --user --force-reinstall --break-system-packages "$PROJECT_ROOT"
  else
    echo "pip reported an externally managed environment and does not support --break-system-packages." >&2
    echo "Please consider using pipx (pipx install bluetooth-bitrate-manager) or a virtualenv." >&2
    exit 1
  fi
fi

APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
DESKTOP_SOURCE="$PROJECT_ROOT/bluetooth_bitrate_manager/resources/bluetooth-bitrate-manager.desktop"
DESKTOP_TARGET="$APP_DIR/bluetooth-bitrate-manager.desktop"

cp "$DESKTOP_SOURCE" "$DESKTOP_TARGET"
chmod +x "$DESKTOP_TARGET"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" || true
fi

echo "✓ Installation complete."
echo "Launch the GUI with 'bluetooth-bitrate-gui' or from your desktop menu."
