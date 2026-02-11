#!/usr/bin/env bash
set -euo pipefail

# This script rebuilds libspa-codec-bluez5-sbc.so with the high-bitpool SBC-XQ patch.

SCRIPT_DIR="$(
  cd -- "$(dirname "${BASH_SOURCE[0]}")"
  pwd
)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Allow override via environment variable (used by GUI)
PATCH_FILE="${PATCH_FILE:-$SCRIPT_DIR/pipewire-sbc-custom-bitpool.patch}"
WORKDIR="${WORKDIR:-$HOME/.cache/pipewire-highbitpool}"
PIPEWIRE_GIT=${PIPEWIRE_GIT:-https://gitlab.freedesktop.org/pipewire/pipewire.git}
PIPEWIRE_TAG="${PIPEWIRE_TAG:-}"
INSTALL_PREFIX="${INSTALL_PREFIX:-}"

run_privileged() {
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    "$@"
    return
  fi

  if command -v pkexec >/dev/null 2>&1; then
    pkexec "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Need elevated privileges to install patched codec (requires pkexec, sudo, or root)." >&2
    exit 1
  fi
}

require_command() {
  local command_name=$1
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
}

detect_pipewire_tag() {
  # Match the host's installed libpipewire version whenever possible.
  if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libpipewire-0.3; then
    local detected_version
    detected_version="$(pkg-config --modversion libpipewire-0.3 2>/dev/null || true)"
    if [[ -n "$detected_version" ]]; then
      # Normalize distro version strings (e.g. 1.4.9+r12 -> 1.4.9).
      detected_version="$(echo "$detected_version" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+).*$/\1/')"
      echo "$detected_version"
      return
    fi
  fi

  # Safe fallback when PipeWire dev metadata is unavailable.
  echo "1.4.9"
}

detect_install_prefix() {
  local so_name="libspa-codec-bluez5-sbc.so"
  local -a candidates=()

  if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libpipewire-0.3; then
    local pkg_libdir
    pkg_libdir="$(pkg-config --variable=libdir libpipewire-0.3 2>/dev/null || true)"
    if [[ -n "$pkg_libdir" ]]; then
      candidates+=("$pkg_libdir/spa-0.2/bluez5")
    fi
  fi

  candidates+=(
    "/usr/lib/spa-0.2/bluez5"
    "/usr/lib64/spa-0.2/bluez5"
    "/usr/local/lib/spa-0.2/bluez5"
    "/usr/local/lib64/spa-0.2/bluez5"
  )

  if command -v dpkg-architecture >/dev/null 2>&1; then
    local deb_multiarch
    deb_multiarch="$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || true)"
    if [[ -n "$deb_multiarch" ]]; then
      candidates=("/usr/lib/$deb_multiarch/spa-0.2/bluez5" "${candidates[@]}")
    fi
  fi

  if command -v gcc >/dev/null 2>&1; then
    local gcc_triplet
    gcc_triplet="$(gcc -dumpmachine 2>/dev/null || true)"
    if [[ -n "$gcc_triplet" ]]; then
      candidates=("/usr/lib/$gcc_triplet/spa-0.2/bluez5" "${candidates[@]}")
    fi
  fi

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate/$so_name" ]]; then
      echo "$candidate"
      return
    fi
  done

  local discovered_file
  discovered_file="$(find /usr/lib /usr/local/lib -maxdepth 6 -type f -name "$so_name" -print -quit 2>/dev/null || true)"
  if [[ -n "$discovered_file" ]]; then
    dirname "$discovered_file"
    return
  fi

  echo "/usr/lib/spa-0.2/bluez5"
}

ensure_pipewire_tag_available() {
  local fallback_tag="1.4.9"
  if [[ -d "$WORKDIR/pipewire/.git" ]] && git -C "$WORKDIR/pipewire" rev-parse -q --verify "$PIPEWIRE_TAG^{commit}" >/dev/null 2>&1; then
    return
  fi

  local remote_tags
  if remote_tags="$(git ls-remote --tags "$PIPEWIRE_GIT" 2>/dev/null)"; then
    local remote_refs
    remote_refs="$(echo "$remote_tags" | awk '{print $2}')"

    if echo "$remote_refs" | grep -Fxq "refs/tags/$PIPEWIRE_TAG"; then
      return
    fi

    echo "Requested PipeWire tag '$PIPEWIRE_TAG' was not found in upstream tags." >&2
    if echo "$remote_refs" | grep -Fxq "refs/tags/$fallback_tag"; then
      echo "Falling back to PipeWire tag '$fallback_tag'." >&2
      PIPEWIRE_TAG="$fallback_tag"
      return
    fi

    echo "Could not find a compatible PipeWire tag automatically. Set PIPEWIRE_TAG manually." >&2
    exit 1
  fi

  echo "Could not verify PipeWire tags remotely; continuing with '$PIPEWIRE_TAG'." >&2
}

restart_audio_stack() {
  local restarted=0

  if ! command -v systemctl >/dev/null 2>&1; then
    echo ">>> systemctl not found; restart PipeWire/WirePlumber manually."
    return 0
  fi

  # Restart whichever services are actually present in this user session.
  local unit
  for unit in pipewire.service pipewire-pulse.service wireplumber.service pipewire-media-session.service; do
    if systemctl --user show "$unit" >/dev/null 2>&1; then
      if systemctl --user restart "$unit" >/dev/null 2>&1; then
        echo ">>> Restarted $unit"
        restarted=1
      fi
    fi
  done

  if [[ $restarted -eq 0 ]]; then
    echo ">>> Could not auto-restart user audio services; please relogin or restart PipeWire manually."
  fi
}

require_command git
require_command curl
require_command meson
require_command ninja
require_command pkg-config

if ! pkg-config --exists dbus-1 glib-2.0; then
  echo "Missing PipeWire build dependencies: dbus-1 and/or glib-2.0 development headers." >&2
  echo "Ubuntu/Debian packages: libdbus-1-dev libglib2.0-dev" >&2
  exit 1
fi

PIPEWIRE_TAG="${PIPEWIRE_TAG:-$(detect_pipewire_tag)}"
INSTALL_PREFIX="${INSTALL_PREFIX:-$(detect_install_prefix)}"
TARGET="$INSTALL_PREFIX/libspa-codec-bluez5-sbc.so"
ensure_pipewire_tag_available

echo ">>> Using work directory: $WORKDIR"
echo ">>> Using PipeWire tag: $PIPEWIRE_TAG"
echo ">>> Using install prefix: $INSTALL_PREFIX"
mkdir -p "$WORKDIR"

if [[ ! -f "$TARGET" ]]; then
  echo "Could not find installed codec at: $TARGET" >&2
  echo "Set INSTALL_PREFIX to your distro's spa bluez5 directory and retry." >&2
  exit 1
fi

if [[ ! -d "$WORKDIR/pipewire" ]]; then
  echo ">>> Cloning PipeWire $PIPEWIRE_TAG"
  if ! git clone --depth 1 --branch "$PIPEWIRE_TAG" "$PIPEWIRE_GIT" "$WORKDIR/pipewire"; then
    if [[ "$PIPEWIRE_TAG" != "1.4.9" ]]; then
      echo ">>> Clone for $PIPEWIRE_TAG failed, retrying with fallback tag 1.4.9"
      PIPEWIRE_TAG="1.4.9"
      rm -rf "$WORKDIR/pipewire"
      git clone --depth 1 --branch "$PIPEWIRE_TAG" "$PIPEWIRE_GIT" "$WORKDIR/pipewire"
    else
      exit 1
    fi
  fi
else
  echo ">>> Reusing existing repo; resetting to $PIPEWIRE_TAG"
  if ! git -C "$WORKDIR/pipewire" fetch --depth 1 origin "refs/tags/$PIPEWIRE_TAG:refs/tags/$PIPEWIRE_TAG"; then
    echo ">>> Could not fetch tag $PIPEWIRE_TAG; attempting to use locally cached sources"
  fi
  if ! git -C "$WORKDIR/pipewire" rev-parse -q --verify "$PIPEWIRE_TAG^{commit}" >/dev/null 2>&1; then
    echo "PipeWire tag '$PIPEWIRE_TAG' is not available in local cache." >&2
    echo "Connect to the internet or set PIPEWIRE_TAG to an existing local tag." >&2
    exit 1
  fi
  git -C "$WORKDIR/pipewire" reset --hard "$PIPEWIRE_TAG"
  git -C "$WORKDIR/pipewire" clean -fdx
fi

cd "$WORKDIR/pipewire"

echo ">>> Applying high-bitpool patch"
if ! git apply --check "$PATCH_FILE"; then
  echo "Patch did not apply cleanly against PipeWire tag $PIPEWIRE_TAG." >&2
  echo "Set PIPEWIRE_TAG to a compatible version, or update the patch." >&2
  exit 1
fi
git apply "$PATCH_FILE"

GDBUS_FALLBACK="$HOME/.local/bin/gdbus-codegen"
if command -v gdbus-codegen >/dev/null 2>&1; then
  export GDBUS_CODEGEN
  GDBUS_CODEGEN="$(command -v gdbus-codegen)"
else
  echo ">>> Fetching gdbus-codegen helper script"
  mkdir -p "$(dirname "$GDBUS_FALLBACK")"
  curl -fsSL https://gitlab.gnome.org/GNOME/glib/-/raw/2.80.5/gio/gdbus-2.0/codegen/gdbus-codegen -o "$GDBUS_FALLBACK"
  chmod +x "$GDBUS_FALLBACK"
  export GDBUS_CODEGEN="$GDBUS_FALLBACK"
fi

echo ">>> Using gdbus-codegen: $GDBUS_CODEGEN"

echo ">>> Setting up Meson build"
meson setup build -Dman=disabled -Ddocs=disabled -Dsession-managers=[] --wipe

echo ">>> Building libspa-codec-bluez5-sbc.so"
if ! meson compile -C build libspa-codec-bluez5-sbc; then
  echo ">>> Targeted build failed; falling back to full build"
  meson compile -C build
fi

BUILD_DIR="$WORKDIR/pipewire/build"
OUTPUT_SO="$BUILD_DIR/spa/plugins/bluez5/libspa-codec-bluez5-sbc.so"
if [[ ! -f "$OUTPUT_SO" ]]; then
  OUTPUT_SO="$(find "$BUILD_DIR" -type f -name 'libspa-codec-bluez5-sbc.so' -print -quit 2>/dev/null || true)"
fi
if [[ -z "${OUTPUT_SO:-}" || ! -f "$OUTPUT_SO" ]]; then
  echo "Failed to build $OUTPUT_SO" >&2
  exit 1
fi

BACKUP="$INSTALL_PREFIX/libspa-codec-bluez5-sbc.so.bak.$(date +%s)"

echo ">>> Backing up current $TARGET to $BACKUP (requires privileges)"
run_privileged cp "$TARGET" "$BACKUP"

echo ">>> Installing patched libspa-codec-bluez5-sbc.so (requires privileges)"
run_privileged cp "$OUTPUT_SO" "$TARGET"

echo ">>> Restarting PipeWire stack"
restart_audio_stack

echo
echo "Patched module installed. Reconnect your Bluetooth device and check the codec with:"
echo "  busctl --system get-property org.bluez /org/bluez/hci0/dev_<ADDR>/sep1/fdX org.bluez.MediaTransport1 Configuration"
echo
echo "If something breaks, restore the backup with:"
echo "  # run as root (e.g. sudo/doas)"
echo "  cp $BACKUP $TARGET && systemctl --user restart pipewire pipewire-pulse wireplumber"
