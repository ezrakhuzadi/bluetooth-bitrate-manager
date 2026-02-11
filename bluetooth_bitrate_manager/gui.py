#!/usr/bin/env python3
"""
Bluetooth Bitrate Manager - GUI Application
Monitors and controls Bluetooth audio bitrate settings
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
import subprocess
import re
import threading
import os
import sys
import shutil
import tempfile
import time
import shlex
from pathlib import Path
from typing import Optional, Sequence
from functools import lru_cache

from . import bitrate_utils

BIN_INSTALL = shutil.which("install") or "/usr/bin/install"
BIN_MKDIR = shutil.which("mkdir") or "/usr/bin/mkdir"
SUDO_PATH = shutil.which("sudo")
PKEXEC_PATH = shutil.which("pkexec")
TRUE_PATH = shutil.which("true") or "/usr/bin/true"
FLATPAK_SPAWN = shutil.which("flatpak-spawn")
IS_FLATPAK = os.path.exists("/.flatpak-info") or os.getenv("FLATPAK_ID")
_sudo_keepalive_thread = None
_sudo_keepalive_lock = threading.Lock()


def _have_tty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def ensure_sudo_ticket():
    """Ensure sudo timestamp is valid and spawn keepalive thread."""
    global _sudo_keepalive_thread
    if not SUDO_PATH:
        raise RuntimeError("sudo not available on PATH")

    check = subprocess.run(
        [SUDO_PATH, "-n", "true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode != 0:
        prompt = subprocess.run([SUDO_PATH, "-v"])
        if prompt.returncode != 0:
            raise RuntimeError("sudo authorization failed")

    with _sudo_keepalive_lock:
        if _sudo_keepalive_thread is None:
            def _keepalive():
                while True:
                    time.sleep(60)
                    result = subprocess.run(
                        [SUDO_PATH, "-n", "-v"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if result.returncode != 0:
                        break

            thread = threading.Thread(target=_keepalive, daemon=True)
            thread.start()
            _sudo_keepalive_thread = thread


def _host_command(args: Sequence[str]) -> Sequence[str]:
    if IS_FLATPAK:
        if not FLATPAK_SPAWN:
            raise RuntimeError("flatpak-spawn not available inside sandbox environment.")
        return ['flatpak-spawn', '--host', *args]
    return args


@lru_cache(maxsize=None)
def _host_has(command: str) -> bool:
    if not IS_FLATPAK:
        return shutil.which(command) is not None
    if not FLATPAK_SPAWN:
        return False
    try:
        check = subprocess.run(
            [FLATPAK_SPAWN, '--host', 'sh', '-c', f'command -v {shlex.quote(command)}'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return check.returncode == 0
    except Exception:
        return False


def run_privileged_command(args, text_input: Optional[str] = None):
    """Execute a command requiring elevated privileges using pkexec or sudo."""
    if IS_FLATPAK:
        if _host_has("pkexec"):
            command = _host_command(['pkexec', *args])
        elif _host_has("sudo"):
            command = _host_command(['sudo', *args])
        elif _host_has(args[0]):
            command = _host_command(list(args))
        else:
            raise RuntimeError("No privileged helper (pkexec/sudo) available on host.")

        return subprocess.run(
            command,
            input=text_input,
            text=True,
            capture_output=True,
        )

    if PKEXEC_PATH:
        command = [PKEXEC_PATH] + args
    elif SUDO_PATH and _have_tty():
        ensure_sudo_ticket()
        command = [SUDO_PATH] + args
    elif SUDO_PATH:
        ensure_sudo_ticket()
        command = [SUDO_PATH] + args
    else:
        raise RuntimeError("Neither pkexec nor sudo is available in PATH.")

    return subprocess.run(
        command,
        input=text_input,
        text=True,
        capture_output=True,
    )


def initialize_privileges():
    """Attempt to cache elevated privileges once at startup."""
    if IS_FLATPAK:
        return

    if SUDO_PATH and _have_tty():
        ensure_sudo_ticket()
        return

    if PKEXEC_PATH:
        result = subprocess.run([PKEXEC_PATH, TRUE_PATH], capture_output=True)
        if result.returncode != 0:
            raise RuntimeError("Privilege escalation cancelled or failed.")
        return

    if SUDO_PATH:
        ensure_sudo_ticket()
        return

    raise RuntimeError("No privilege escalation mechanism available.")


class BluetoothDevice:
    """Represents a Bluetooth audio device"""
    def __init__(self, name="Unknown", description="Unknown", codec="Unknown",
                 bitrate="Unknown", rate="Unknown", channels="Unknown",
                 channel_mode="Unknown", block_length="Unknown", subbands="Unknown",
                 codec_raw=""):
        self.name = name
        self.description = description
        self.codec = codec
        self.bitrate = bitrate
        self.rate = rate
        self.channels = channels
        self.channel_mode = channel_mode
        self.block_length = block_length
        self.subbands = subbands
        self.codec_raw = codec_raw


class BitrateMonitor:
    """Monitors Bluetooth device bitrates"""

    @staticmethod
    def get_bluetooth_devices():
        """Get Bluetooth audio devices and their codec info"""
        try:
            result = subprocess.run(['pactl', 'list', 'sinks'],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return []

            devices = []
            current_device = None

            for line in result.stdout.split('\n'):
                if line.startswith('Sink #'):
                    if current_device and current_device.get('is_bluetooth'):
                        device = BluetoothDevice(
                            name=current_device.get('name', 'Unknown'),
                            description=current_device.get('description', 'Unknown'),
                            codec=current_device.get('codec', 'Unknown'),
                            bitrate=current_device.get('bitrate', 'Unknown'),
                            rate=current_device.get('rate', 'Unknown'),
                            channels=current_device.get('channels', 'Unknown'),
                            channel_mode=current_device.get('channel_mode', 'Unknown'),
                            block_length=current_device.get('block_length', 'Unknown'),
                            subbands=current_device.get('subbands', 'Unknown'),
                            codec_raw=current_device.get('codec_raw', '')
                        )
                        devices.append(device)
                    current_device = {
                        'is_bluetooth': False,
                        'channel_mode': 'Unknown',
                        'block_length': 'Unknown',
                        'subbands': 'Unknown'
                    }
                elif current_device:
                    if 'Name:' in line:
                        name = line.split(':', 1)[1].strip()
                        current_device['name'] = name
                        if 'bluez' in name:
                            current_device['is_bluetooth'] = True
                    elif 'Description:' in line:
                        current_device['description'] = line.split(':', 1)[1].strip()
                    elif 'api.bluez5.address' in line:
                        address = line.split('=')[1].strip().strip('"')
                        current_device['address'] = address
                    elif 'api.bluez5.codec' in line:
                        codec = line.split('=')[1].strip().strip('"')
                        current_device['codec_raw'] = codec
                        # Decode codec names
                        if 'sbc' in codec.lower():
                            if 'xq' in codec.lower():
                                current_device['codec'] = 'SBC XQ'
                                # Try to get actual bitpool for SBC
                                if 'address' in current_device:
                                    config = bitrate_utils.fetch_sbc_configuration(current_device['address'])
                                    if config:
                                        bitrate_value = bitrate_utils.sbc_bitrate_from_config(config)
                                        bitpool = config.effective_bitpool
                                        if bitrate_value and bitpool is not None:
                                            formatted = bitrate_utils.format_bitrate(bitrate_value)
                                            current_device['bitrate'] = f'{formatted} (bitpool {bitpool})'
                                        else:
                                            current_device['bitrate'] = '~552 kbps (est.)'
                                        if config.sample_rate:
                                            current_device['rate'] = str(config.sample_rate)
                                        if config.channel_mode:
                                            mode_label = bitrate_utils.format_channel_mode(config.channel_mode)
                                            if mode_label:
                                                current_device['channel_mode'] = mode_label
                                        if config.block_length:
                                            current_device['block_length'] = str(config.block_length)
                                        if config.subbands:
                                            current_device['subbands'] = str(config.subbands)
                                    else:
                                        current_device['bitrate'] = '~552 kbps (est.)'
                                else:
                                    current_device['bitrate'] = '~552 kbps (est.)'
                            else:
                                current_device['codec'] = 'SBC'
                                # Standard SBC estimation
                                if 'address' in current_device:
                                    config = bitrate_utils.fetch_sbc_configuration(current_device['address'])
                                    if config:
                                        bitrate_value = bitrate_utils.sbc_bitrate_from_config(config)
                                        bitpool = config.effective_bitpool
                                        if bitrate_value and bitpool is not None:
                                            formatted = bitrate_utils.format_bitrate(bitrate_value)
                                            current_device['bitrate'] = f'{formatted} (bitpool {bitpool})'
                                        else:
                                            current_device['bitrate'] = '~328 kbps (est.)'
                                        if config.sample_rate:
                                            current_device['rate'] = str(config.sample_rate)
                                        if config.channel_mode:
                                            mode_label = bitrate_utils.format_channel_mode(config.channel_mode)
                                            if mode_label:
                                                current_device['channel_mode'] = mode_label
                                        if config.block_length:
                                            current_device['block_length'] = str(config.block_length)
                                        if config.subbands:
                                            current_device['subbands'] = str(config.subbands)
                                    else:
                                        current_device['bitrate'] = '~328 kbps (est.)'
                                else:
                                    current_device['bitrate'] = '~328 kbps (est.)'
                        elif 'aac' in codec.lower():
                            current_device['codec'] = 'AAC'
                            current_device['bitrate'] = '~256 kbps'
                        elif 'aptx_hd' in codec.lower():
                            current_device['codec'] = 'aptX HD'
                            current_device['bitrate'] = '576 kbps'
                        elif 'aptx' in codec.lower():
                            current_device['codec'] = 'aptX'
                            current_device['bitrate'] = '352 kbps'
                        elif 'ldac' in codec.lower():
                            current_device['codec'] = 'LDAC'
                            if 'hq' in codec.lower():
                                current_device['bitrate'] = '~990 kbps'
                            elif 'sq' in codec.lower():
                                current_device['bitrate'] = '~660 kbps'
                            else:
                                current_device['bitrate'] = '~330-990 kbps'
                        elif 'msbc' in codec.lower():
                            current_device['codec'] = 'mSBC'
                            current_device['bitrate'] = '~64 kbps'
                        elif 'cvsd' in codec.lower():
                            current_device['codec'] = 'CVSD'
                            current_device['bitrate'] = '~64 kbps'
                        else:
                            current_device['codec'] = codec.upper()
                    elif 'Sample Specification:' in line:
                        spec = line.split(':', 1)[1].strip()
                        match = re.search(r'(\d+)ch\s+(\d+)Hz', spec)
                        if match:
                            current_device['channels'] = match.group(1)
                            current_device['rate'] = match.group(2)

            if current_device and current_device.get('is_bluetooth'):
                device = BluetoothDevice(
                    name=current_device.get('name', 'Unknown'),
                    description=current_device.get('description', 'Unknown'),
                    codec=current_device.get('codec', 'Unknown'),
                    bitrate=current_device.get('bitrate', 'Unknown'),
                    rate=current_device.get('rate', 'Unknown'),
                    channels=current_device.get('channels', 'Unknown'),
                    channel_mode=current_device.get('channel_mode', 'Unknown'),
                    block_length=current_device.get('block_length', 'Unknown'),
                    subbands=current_device.get('subbands', 'Unknown'),
                    codec_raw=current_device.get('codec_raw', '')
                )
                devices.append(device)

            return devices

        except Exception as e:
            print(f"Error getting device info: {e}", file=sys.stderr)
            return []


class BluetoothBitrateWindow(Adw.ApplicationWindow):
    """Main application window"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_default_size(700, 600)
        self.set_title("Bluetooth Bitrate Manager")

        # Main container
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)

        # Header bar
        header = Adw.HeaderBar()
        self.main_box.append(header)

        # Create notebook (tabs)
        self.notebook = Gtk.Notebook()
        self.notebook.set_margin_start(12)
        self.notebook.set_margin_end(12)
        self.notebook.set_margin_top(12)
        self.notebook.set_margin_bottom(12)
        self.main_box.append(self.notebook)

        # Tab 1: Monitor
        self.create_monitor_tab()

        # Tab 2: Configure SBC-XQ
        self.create_config_tab()

        # Start monitoring
        self.monitoring = True
        self.start_monitoring()

    def create_monitor_tab(self):
        """Create the monitoring tab"""
        monitor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        monitor_box.set_margin_start(12)
        monitor_box.set_margin_end(12)
        monitor_box.set_margin_top(12)
        monitor_box.set_margin_bottom(12)

        # Status label
        self.status_label = Gtk.Label()
        self.status_label.set_markup("<b>Status:</b> Monitoring...")
        self.status_label.set_halign(Gtk.Align.START)
        monitor_box.append(self.status_label)

        # Scrolled window for device list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        monitor_box.append(scrolled)

        # Device list container
        self.device_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scrolled.set_child(self.device_list_box)

        # Refresh button
        refresh_btn = Gtk.Button(label="Refresh Now")
        refresh_btn.connect("clicked", self.on_refresh_clicked)
        monitor_box.append(refresh_btn)

        self.notebook.append_page(monitor_box, Gtk.Label(label="Monitor"))

    def create_config_tab(self):
        """Create the configuration tab"""
        config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        config_box.set_margin_start(12)
        config_box.set_margin_end(12)
        config_box.set_margin_top(12)
        config_box.set_margin_bottom(12)

        # Title
        title = Gtk.Label()
        title.set_markup("<b>SBC-XQ High Bitrate Configuration</b>")
        title.set_halign(Gtk.Align.START)
        config_box.append(title)

        # Description
        desc = Gtk.Label()
        desc.set_text("Enable SBC-XQ with high bitpool settings for better audio quality.\n"
                     "This will build and install a patched PipeWire codec library.\n"
                     "It does not force codec selection; your system still negotiates SBC/SBC-XQ.")
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.START)
        config_box.append(desc)

        # Sample rate selection
        rate_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        rate_label = Gtk.Label(label="Sample Rate:")
        rate_label.set_halign(Gtk.Align.START)
        rate_box.append(rate_label)

        # Use DropDown with StringList to avoid deprecation warnings
        rate_strings = Gtk.StringList()
        rate_strings.append("44100 Hz")
        rate_strings.append("48000 Hz")
        self.rate_combo = Gtk.DropDown(model=rate_strings)
        self.rate_combo.set_selected(0)
        self.rate_combo.connect("notify::selected", self.on_rate_changed)
        rate_box.append(self.rate_combo)
        config_box.append(rate_box)

        # Enable SBC-XQ checkbox
        self.sbc_xq_check = Gtk.CheckButton(label="Enable SBC-XQ")
        self.sbc_xq_check.set_active(True)
        config_box.append(self.sbc_xq_check)

        # Bitpool slider section
        bitpool_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bitpool_box.set_margin_top(6)

        bitpool_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bitpool_label = Gtk.Label(label="Target Bitpool:")
        bitpool_label.set_halign(Gtk.Align.START)
        bitpool_header_box.append(bitpool_label)

        self.bitpool_value_label = Gtk.Label()
        default_bps = bitrate_utils.calculate_sbc_bitrate(
            bitpool=47,
            sample_rate=44100,
            channel_mode='dual_channel',
            block_length=16,
            subbands=8,
        )
        self.bitpool_value_label.set_markup(
            f"<b>47</b> (~{bitrate_utils.format_bitrate(default_bps)})"
        )
        self.bitpool_value_label.set_halign(Gtk.Align.END)
        self.bitpool_value_label.set_hexpand(True)
        bitpool_header_box.append(self.bitpool_value_label)
        bitpool_box.append(bitpool_header_box)

        # Bitpool slider (range 20-84, default 47)
        self.bitpool_adjustment = Gtk.Adjustment(
            value=47,
            lower=20,
            upper=84,
            step_increment=1,
            page_increment=10,
            page_size=0
        )
        self.bitpool_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=self.bitpool_adjustment
        )
        self.bitpool_slider.set_draw_value(False)
        self.bitpool_slider.set_hexpand(True)
        # Marks show 44.1kHz values (will update in real-time above)
        self.bitpool_slider.add_mark(32, Gtk.PositionType.BOTTOM, "Standard\n386 kbps")
        self.bitpool_slider.add_mark(47, Gtk.PositionType.BOTTOM, "SBC-XQ\n551 kbps")
        self.bitpool_slider.add_mark(64, Gtk.PositionType.BOTTOM, "Very High\n738 kbps")
        self.bitpool_slider.connect("value-changed", self.on_bitpool_changed)
        bitpool_box.append(self.bitpool_slider)

        # Info label
        bitpool_info = Gtk.Label()
        bitpool_info.set_markup("<small>Higher bitpool = higher bitrate, but not all devices support values above 53</small>")
        bitpool_info.set_wrap(True)
        bitpool_info.set_halign(Gtk.Align.START)
        bitpool_info.add_css_class("dim-label")
        bitpool_box.append(bitpool_info)

        config_box.append(bitpool_box)

        # Build and install button
        build_btn = Gtk.Button(label="Build and Install High Bitrate Codec")
        build_btn.connect("clicked", self.on_build_clicked)
        build_btn.add_css_class("suggested-action")
        config_box.append(build_btn)

        # Status/log view
        log_label = Gtk.Label(label="Build Output:")
        log_label.set_halign(Gtk.Align.START)
        config_box.append(log_label)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        config_box.append(scrolled)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_buffer = self.log_view.get_buffer()
        scrolled.set_child(self.log_view)

        # Quick actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        restart_btn = Gtk.Button(label="Restart PipeWire")
        restart_btn.connect("clicked", self.on_restart_pipewire)
        actions_box.append(restart_btn)

        bt_restart_btn = Gtk.Button(label="Restart Bluetooth")
        bt_restart_btn.connect("clicked", self.on_restart_bluetooth)
        actions_box.append(bt_restart_btn)

        config_box.append(actions_box)

        self.notebook.append_page(config_box, Gtk.Label(label="Configure"))

    def update_device_display(self):
        """Update the device list display"""
        # Clear existing widgets
        child = self.device_list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.device_list_box.remove(child)
            child = next_child

        devices = BitrateMonitor.get_bluetooth_devices()

        if not devices:
            no_devices = Gtk.Label(label="No Bluetooth audio devices found")
            no_devices.set_halign(Gtk.Align.CENTER)
            no_devices.set_valign(Gtk.Align.CENTER)
            self.device_list_box.append(no_devices)
            return

        for i, device in enumerate(devices, 1):
            # Create a card for each device
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("card")
            card.set_margin_start(6)
            card.set_margin_end(6)
            card.set_margin_top(6)
            card.set_margin_bottom(6)

            # Device header
            header = Gtk.Label()
            header.set_markup(f"<b>Device {i}: {device.description}</b>")
            header.set_halign(Gtk.Align.START)
            header.set_margin_start(12)
            header.set_margin_top(12)
            card.append(header)

            # Device info grid
            grid = Gtk.Grid()
            grid.set_column_spacing(12)
            grid.set_row_spacing(6)
            grid.set_margin_start(24)
            grid.set_margin_end(12)
            grid.set_margin_top(6)
            grid.set_margin_bottom(12)

            # Codec
            codec_label = Gtk.Label(label="Codec:")
            codec_label.set_halign(Gtk.Align.START)
            codec_value = Gtk.Label(label=device.codec)
            codec_value.set_halign(Gtk.Align.START)
            codec_value.add_css_class("monospace")
            if device.codec == "SBC XQ":
                codec_value.add_css_class("success")
            grid.attach(codec_label, 0, 0, 1, 1)
            grid.attach(codec_value, 1, 0, 1, 1)

            # Bitrate
            bitrate_label = Gtk.Label(label="Bitrate:")
            bitrate_label.set_halign(Gtk.Align.START)
            bitrate_value = Gtk.Label(label=device.bitrate)
            bitrate_value.set_halign(Gtk.Align.START)
            bitrate_value.add_css_class("monospace")
            grid.attach(bitrate_label, 0, 1, 1, 1)
            grid.attach(bitrate_value, 1, 1, 1, 1)

            # Sample rate
            if device.rate != "Unknown":
                rate_label = Gtk.Label(label="Sample Rate:")
                rate_label.set_halign(Gtk.Align.START)
                rate_value = Gtk.Label(label=f"{device.rate} Hz")
                rate_value.set_halign(Gtk.Align.START)
                rate_value.add_css_class("monospace")
                grid.attach(rate_label, 0, 2, 1, 1)
                grid.attach(rate_value, 1, 2, 1, 1)

            # Channel mode
            if device.channel_mode != "Unknown":
                mode_label = Gtk.Label(label="Channel Mode:")
                mode_label.set_halign(Gtk.Align.START)
                mode_value = Gtk.Label(label=device.channel_mode)
                mode_value.set_halign(Gtk.Align.START)
                mode_value.add_css_class("monospace")
                grid.attach(mode_label, 0, 3, 1, 1)
                grid.attach(mode_value, 1, 3, 1, 1)

            if device.block_length != "Unknown" or device.subbands != "Unknown":
                frame_label = Gtk.Label(label="SBC Frame:")
                frame_label.set_halign(Gtk.Align.START)
                parts = []
                if device.block_length != "Unknown":
                    parts.append(f"{device.block_length} blocks")
                if device.subbands != "Unknown":
                    parts.append(f"{device.subbands} subbands")
                frame_value = Gtk.Label(label=" / ".join(parts) if parts else "Unknown")
                frame_value.set_halign(Gtk.Align.START)
                frame_value.add_css_class("monospace")
                grid.attach(frame_label, 0, 4, 1, 1)
                grid.attach(frame_value, 1, 4, 1, 1)

            # Channels
            if device.channels != "Unknown":
                ch_label = Gtk.Label(label="Channels:")
                ch_label.set_halign(Gtk.Align.START)
                ch_value = Gtk.Label(label=device.channels)
                ch_value.set_halign(Gtk.Align.START)
                ch_value.add_css_class("monospace")
                grid.attach(ch_label, 0, 5, 1, 1)
                grid.attach(ch_value, 1, 5, 1, 1)

            card.append(grid)
            self.device_list_box.append(card)

        return False  # Don't repeat if called from GLib.idle_add

    def start_monitoring(self):
        """Start the monitoring loop"""
        def monitor_loop():
            while self.monitoring:
                GLib.idle_add(self.update_device_display)
                GLib.timeout_add_seconds(2, lambda: None)
                import time
                time.sleep(2)

        thread = threading.Thread(target=monitor_loop, daemon=True)
        thread.start()

    def request_initial_privileges(self):
        """Prompt for elevated privileges once when the app starts."""
        def worker():
            try:
                initialize_privileges()
                GLib.idle_add(self.log_to_buffer, "✓ Privileges ready\n")
            except Exception as exc:
                GLib.idle_add(self.log_to_buffer, f"⚠ {exc}\n")

        threading.Thread(target=worker, daemon=True).start()

    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        self.update_device_display()

    def calculate_sbc_bitrate(self, bitpool, sample_rate):
        """Calculate dual-channel SBC bitrate"""
        bitrate = bitrate_utils.calculate_sbc_bitrate(
            bitpool=bitpool,
            sample_rate=sample_rate,
            channel_mode='dual_channel',
            block_length=16,
            subbands=8,
        )
        return bitrate if bitrate is not None else 0

    def on_rate_changed(self, dropdown, _param):
        """Handle sample rate dropdown change"""
        # Update bitrate display when sample rate changes
        bitpool = int(self.bitpool_slider.get_value())
        sample_rate = 44100 if dropdown.get_selected() == 0 else 48000
        bitrate_bps = self.calculate_sbc_bitrate(bitpool, sample_rate)
        formatted = bitrate_utils.format_bitrate(bitrate_bps)
        self.bitpool_value_label.set_markup(f"<b>{bitpool}</b> (~{formatted})")

    def on_bitpool_changed(self, scale):
        """Handle bitpool slider change"""
        bitpool = int(scale.get_value())
        # Get selected sample rate
        sample_rate = 44100 if self.rate_combo.get_selected() == 0 else 48000
        bitrate_bps = self.calculate_sbc_bitrate(bitpool, sample_rate)
        formatted = bitrate_utils.format_bitrate(bitrate_bps)
        self.bitpool_value_label.set_markup(f"<b>{bitpool}</b> (~{formatted})")

    def on_build_clicked(self, button):
        """Handle build button click"""
        button.set_sensitive(False)
        self.log_to_buffer("Starting build process...\n")

        def build_thread():
            try:
                # Get configuration
                rate = "44100" if self.rate_combo.get_selected() == 0 else "48000"
                enable_xq = self.sbc_xq_check.get_active()
                bitpool = int(self.bitpool_slider.get_value())

                # Use the same bitpool value for both sample rates unless user overrides
                bitpool_48k = bitpool

                GLib.idle_add(self.log_to_buffer,
                            f"Configuration: rate={rate}, sbc-xq={enable_xq}, bitpool={bitpool}\n")

                # Generate custom patch
                repo_root = Path(__file__).resolve().parent
                resources_dir = repo_root / "resources"

                # Write to user cache directory instead of system package directory
                cache_dir = Path.home() / ".cache" / "bluetooth-bitrate-manager"
                cache_dir.mkdir(parents=True, exist_ok=True)
                custom_patch_path = cache_dir / "pipewire-sbc-custom-bitpool.patch"

                patch_content = f"""diff --git a/spa/plugins/bluez5/a2dp-codec-sbc.c b/spa/plugins/bluez5/a2dp-codec-sbc.c
index fc55a03..935a4e0 100644
--- a/spa/plugins/bluez5/a2dp-codec-sbc.c
+++ b/spa/plugins/bluez5/a2dp-codec-sbc.c
@@ -79,8 +79,10 @@ static uint8_t default_bitpool(uint8_t freq, uint8_t mode, bool xq)
 	case SBC_SAMPLING_FREQ_44100:
 		switch (mode) {{
 		case SBC_CHANNEL_MODE_MONO:
-		case SBC_CHANNEL_MODE_DUAL_CHANNEL:
 			return xq ? 43 : 32;
+		case SBC_CHANNEL_MODE_DUAL_CHANNEL:
+			/* Custom bitpool {bitpool} for dual channel SBC-XQ at 44.1 kHz */
+			return xq ? {bitpool} : 32;

 		case SBC_CHANNEL_MODE_STEREO:
 		case SBC_CHANNEL_MODE_JOINT_STEREO:
@@ -90,8 +92,10 @@ static uint8_t default_bitpool(uint8_t freq, uint8_t mode, bool xq)
 	case SBC_SAMPLING_FREQ_48000:
 		switch (mode) {{
 		case SBC_CHANNEL_MODE_MONO:
-		case SBC_CHANNEL_MODE_DUAL_CHANNEL:
 			return xq ? 39 : 29;
+		case SBC_CHANNEL_MODE_DUAL_CHANNEL:
+			/* Custom bitpool {bitpool_48k} for dual channel SBC-XQ at 48 kHz */
+			return xq ? {bitpool_48k} : 29;

 		case SBC_CHANNEL_MODE_STEREO:
 		case SBC_CHANNEL_MODE_JOINT_STEREO:
@@ -204,8 +208,14 @@ static int codec_select_config(const struct media_codec *codec, uint32_t flags,

 	bitpool = default_bitpool(conf.frequency, conf.channel_mode, xq);

-	conf.min_bitpool = SPA_MAX(SBC_MIN_BITPOOL, conf.min_bitpool);
-	conf.max_bitpool = SPA_MIN(bitpool, conf.max_bitpool);
+	if (xq && conf.channel_mode == SBC_CHANNEL_MODE_DUAL_CHANNEL) {{
+		/* Override sink limits: enforce high bitpool for SBC-XQ dual channel. */
+		conf.min_bitpool = bitpool;
+		conf.max_bitpool = bitpool;
+	}} else {{
+		conf.min_bitpool = SPA_MAX(SBC_MIN_BITPOOL, conf.min_bitpool);
+		conf.max_bitpool = SPA_MIN(bitpool, conf.max_bitpool);
+	}}
 	memcpy(config, &conf, sizeof(conf));

 	return sizeof(conf);
"""

                with open(custom_patch_path, 'w') as f:
                    f.write(patch_content)

                GLib.idle_add(self.log_to_buffer,
                            f"Generated custom patch with bitpool {bitpool}\n")

                # Configure WirePlumber first
                GLib.idle_add(self.log_to_buffer,
                            f"Configuring WirePlumber (rate={rate}, sbc-xq={enable_xq})...\n")

                config_content = f"""monitor.bluez.properties = {{
  bluez5.enable-sbc-xq = {str(enable_xq).lower()}
  bluez5.default.rate = {rate}
}}
"""

                config_dir = Path("/etc/wireplumber/wireplumber.conf.d")
                config_path = config_dir / "51-bluetooth.conf"

                try:
                    mkdir_result = run_privileged_command([BIN_MKDIR, "-p", str(config_dir)])
                    if mkdir_result.returncode != 0:
                        GLib.idle_add(
                            self.log_to_buffer,
                            f"Error creating {config_dir}: {mkdir_result.stderr or mkdir_result.stdout}\n"
                        )
                    else:
                        # Create temp file in home dir so it's accessible from host when in Flatpak
                        temp_dir = Path.home() / ".cache" / "bluetooth-bitrate-manager"
                        temp_dir.mkdir(parents=True, exist_ok=True)
                        temp_path = temp_dir / "wireplumber-config.tmp"

                        with open(temp_path, "w") as tmp_file:
                            tmp_file.write(config_content)

                        try:
                            install_result = run_privileged_command(
                                [BIN_INSTALL, "-m644", str(temp_path), str(config_path)]
                            )
                            if install_result.returncode == 0:
                                GLib.idle_add(
                                    self.log_to_buffer,
                                    f"WirePlumber configured at {config_path}\n"
                                )
                            else:
                                GLib.idle_add(
                                    self.log_to_buffer,
                                    "Error installing WirePlumber config: "
                                    f"{install_result.stderr or install_result.stdout}\n"
                                )
                        finally:
                            try:
                                temp_path.unlink(missing_ok=True)
                            except OSError:
                                pass
                except RuntimeError as exc:
                    GLib.idle_add(
                        self.log_to_buffer,
                        f"Privilege escalation failed while configuring WirePlumber: {exc}\n"
                    )

                # Run build script with custom patch
                GLib.idle_add(self.log_to_buffer, "\nRunning build script with custom bitpool patch...\n")

                # Set environment variable to use custom patch
                env = os.environ.copy()
                env['PATCH_FILE'] = str(custom_patch_path)

                # Get the script directory
                build_script = resources_dir / "build_high_bitpool.sh"

                if not build_script.exists():
                    GLib.idle_add(self.log_to_buffer,
                                f"Error: Build script not found at {build_script}\n")
                    GLib.idle_add(button.set_sensitive, True)
                    return

                # Detect if running in Flatpak
                is_flatpak = os.path.exists('/.flatpak-info') or os.getenv('FLATPAK_ID')

                if is_flatpak:
                    # Copy build script and patch to host-accessible location
                    host_script_dir = Path.home() / '.local/share/bluetooth-bitrate-manager'
                    host_script_dir.mkdir(parents=True, exist_ok=True)
                    host_build_script = host_script_dir / 'build_high_bitpool.sh'
                    host_patch = host_script_dir / 'custom_patch.diff'

                    # Copy files to host-accessible location
                    shutil.copy2(str(build_script), str(host_build_script))
                    shutil.copy2(str(custom_patch_path), str(host_patch))

                    # Make script executable
                    host_build_script.chmod(0o755)

                    # Execute on host with host PATH/toolchain. Only pass PATCH_FILE.
                    command = [
                        'flatpak-spawn', '--host',
                        '--env=PATCH_FILE=' + str(host_patch),
                        'bash', str(host_build_script)
                    ]

                    GLib.idle_add(self.log_to_buffer,
                                "Running build script on host system (outside sandbox)...\n")
                else:
                    # Normal execution (non-Flatpak)
                    command = ['bash', str(build_script)]

                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env
                )

                for line in process.stdout:
                    GLib.idle_add(self.log_to_buffer, line)

                process.wait()

                if process.returncode == 0:
                    GLib.idle_add(self.log_to_buffer,
                                "\n✓ Build completed successfully!\n")
                    GLib.idle_add(self.log_to_buffer,
                                "Reconnect your Bluetooth device to use the new codec.\n")
                else:
                    GLib.idle_add(self.log_to_buffer,
                                f"\n✗ Build failed with code {process.returncode}\n")

            except Exception as e:
                GLib.idle_add(self.log_to_buffer, f"\nError: {e}\n")
            finally:
                GLib.idle_add(button.set_sensitive, True)

        thread = threading.Thread(target=build_thread, daemon=True)
        thread.start()

    def on_restart_pipewire(self, button):
        """Restart PipeWire services"""
        self.log_to_buffer("Restarting PipeWire...\n")
        try:
            command = _host_command([
                'systemctl', '--user', 'restart',
                'pipewire', 'pipewire-pulse', 'wireplumber'
            ])
            result = subprocess.run(
                command,
                capture_output=True, text=True
            )
            if result.returncode == 0:
                self.log_to_buffer("✓ PipeWire restarted successfully\n")
            else:
                self.log_to_buffer(f"✗ Failed to restart PipeWire: {result.stderr}\n")
        except Exception as e:
            self.log_to_buffer(f"✗ Error: {e}\n")

    def on_restart_bluetooth(self, button):
        """Restart Bluetooth daemon"""
        self.log_to_buffer("Restarting Bluetooth service...\n")
        try:
            # Try system-level bluetooth service first
            result = run_privileged_command(
                ["systemctl", "restart", "bluetooth.service"]
            )
            if result.returncode != 0 and "Unknown operation" in (result.stderr or ""):
                # Fall back to legacy bluetoothd restart
                result = run_privileged_command(["systemctl", "restart", "bluetooth"])

            if result.returncode == 0:
                self.log_to_buffer("✓ Bluetooth service restarted successfully\n")
            else:
                self.log_to_buffer(
                    f"✗ Failed to restart Bluetooth: {result.stderr or result.stdout}\n"
                )
        except Exception as e:
            self.log_to_buffer(f"✗ Error restarting Bluetooth: {e}\n")

    def log_to_buffer(self, text):
        """Add text to the log buffer"""
        end_iter = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end_iter, text)

        # Auto-scroll to bottom
        mark = self.log_buffer.create_mark(None, end_iter, False)
        self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

        return False  # For GLib.idle_add

    def do_close_request(self):
        """Handle window close"""
        self.monitoring = False
        return False


class BluetoothBitrateApp(Adw.Application):
    """Main application"""

    def __init__(self):
        super().__init__(application_id='com.github.ezrakhuzadi.BluetoothBitrateManager')
        self.window = None

        # Enable dark theme support - follow system preference
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)

    def do_activate(self):
        """Activate the application"""
        if not self.window:
            self.window = BluetoothBitrateWindow(application=self)
        self.window.present()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point"""
    app = BluetoothBitrateApp()
    args = sys.argv if argv is None else [sys.argv[0], *list(argv)]
    return app.run(args)


if __name__ == '__main__':
    sys.exit(main())
