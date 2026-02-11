#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(
  cd -- "$(dirname "${BASH_SOURCE[0]}")"
  pwd
)"
PROJECT_ROOT="$SCRIPT_DIR"

echo "Bluetooth Bitrate Manager installer"
echo "-----------------------------------"

ADMIN_TOOL=""
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  ADMIN_TOOL="root"
elif command -v sudo >/dev/null 2>&1; then
  ADMIN_TOOL="sudo"
elif command -v doas >/dev/null 2>&1; then
  ADMIN_TOOL="doas"
else
  echo "Error: need root privileges (run as root or install sudo/doas)." >&2
  exit 1
fi

admin_run() {
  if [[ $ADMIN_TOOL == "root" ]]; then
    "$@"
  elif [[ $ADMIN_TOOL == "sudo" ]]; then
    sudo "$@"
  else
    doas "$@"
  fi
}

if [[ $ADMIN_TOOL == "sudo" ]]; then
  echo "Requesting administrator privileges up front..."
  sudo -v

  # Keep sudo timestamp fresh while the script runs.
  while true; do
    sudo -v
    sleep 60
  done &
  KEEPALIVE_PID=$!
  trap 'kill "$KEEPALIVE_PID" 2>/dev/null || true' EXIT
elif [[ $ADMIN_TOOL == "doas" ]]; then
  echo "Checking administrator privileges via doas..."
  doas true
else
  echo "Running as root; package installs will not use sudo/doas."
fi

detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  elif command -v zypper >/dev/null 2>&1; then
    echo "zypper"
  elif command -v apk >/dev/null 2>&1; then
    echo "apk"
  elif command -v xbps-install >/dev/null 2>&1; then
    echo "xbps"
  elif command -v eopkg >/dev/null 2>&1; then
    echo "eopkg"
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
      if ! admin_run apt-get update; then
        return 1
      fi
      if ! admin_run apt-get install -y --no-install-recommends "${packages[@]}"; then
        return 1
      fi
      ;;
    dnf)
      if ! admin_run dnf install -y "${packages[@]}"; then
        return 1
      fi
      ;;
    yum)
      if ! admin_run yum install -y "${packages[@]}"; then
        return 1
      fi
      ;;
    pacman)
      if ! admin_run pacman -Sy --needed "${packages[@]}"; then
        return 1
      fi
      ;;
    zypper)
      if ! admin_run zypper refresh; then
        return 1
      fi
      if ! admin_run zypper install -y "${packages[@]}"; then
        return 1
      fi
      ;;
    apk)
      if ! admin_run apk add --no-cache "${packages[@]}"; then
        return 1
      fi
      ;;
    xbps)
      if ! admin_run xbps-install -S -y "${packages[@]}"; then
        return 1
      fi
      ;;
    eopkg)
      if ! admin_run eopkg install -y "${packages[@]}"; then
        return 1
      fi
      ;;
    emerge)
      if ! admin_run emerge --update --newuse "${packages[@]}"; then
        return 1
      fi
      ;;
    *)
      echo "Warning: unsupported package manager. Please install dependencies manually:"
      printf '  %s\n' "${packages[@]}"
      ;;
  esac
}

safe_install_packages() {
  local manager=$1
  shift
  if ! install_packages "$manager" "$@"; then
    echo "Warning: automatic dependency install failed for '$manager'."
    echo "Proceeding; you may need to install missing packages manually."
  fi
}

case "$PKG_MANAGER" in
  apt)
    safe_install_packages apt \
      python3 python3-pip python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
      pipewire wireplumber meson ninja-build gcc pkg-config curl git \
      libdbus-1-dev libglib2.0-dev
    ;;
  dnf)
    safe_install_packages dnf \
      python3 python3-pip python3-gobject gtk4 libadwaita \
      pipewire pipewire-alsa pipewire-pulseaudio wireplumber \
      meson ninja-build gcc make pkgconf curl git dbus-devel glib2-devel
    ;;
  yum)
    safe_install_packages yum \
      python3 python3-pip python3-gobject gtk4 libadwaita \
      pipewire wireplumber \
      meson ninja-build gcc make pkgconf-pkg-config curl git dbus-devel glib2-devel
    ;;
  pacman)
    safe_install_packages pacman \
      python python-pip python-gobject gtk4 libadwaita \
      pipewire wireplumber meson ninja gcc pkgconf curl git
    ;;
  zypper)
    safe_install_packages zypper \
      python311 python311-pip python311-gobject gtk4 libadwaita \
      pipewire wireplumber meson ninja gcc pkg-config curl git dbus-1-devel glib2-devel
    ;;
  apk)
    safe_install_packages apk \
      python3 py3-pip py3-gobject3 gtk4.0 libadwaita \
      pipewire wireplumber meson ninja gcc musl-dev pkgconf curl git dbus-dev glib-dev
    ;;
  xbps)
    safe_install_packages xbps \
      python3 python3-pip python3-gobject gtk4 libadwaita \
      pipewire wireplumber meson ninja gcc pkg-config curl git dbus-devel glib-devel
    ;;
  eopkg)
    safe_install_packages eopkg \
      python3 python3-pip python3-gobject gtk4 libadwaita \
      pipewire wireplumber meson ninja gcc pkg-config curl git dbus-devel glib2-devel
    ;;
  emerge)
    safe_install_packages emerge \
      dev-lang/python dev-python/pip dev-python/pygobject dev-libs/glib \
      gui-libs/gtk gui-libs/libadwaita media-video/pipewire media-video/wireplumber \
      dev-util/meson dev-util/ninja sys-devel/gcc virtual/pkgconfig net-misc/curl dev-vcs/git
    ;;
  *)
    echo "Continuing without automatic dependency installation."
    ;;
esac

PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Error: python3/python is not available on PATH." >&2
    exit 1
  fi
fi

echo "Installing Bluetooth Bitrate Manager (user site-packages)..."
"$PYTHON_BIN" -m pip install --user --upgrade pip >/dev/null 2>&1 || true
if "$PYTHON_BIN" -m pip install --user --force-reinstall "$PROJECT_ROOT"; then
  :
else
  if "$PYTHON_BIN" -m pip help install 2>/dev/null | grep -q -- '--break-system-packages'; then
    echo "Detected externally managed Python environment; retrying with --break-system-packages."
    "$PYTHON_BIN" -m pip install --user --force-reinstall --break-system-packages "$PROJECT_ROOT"
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
