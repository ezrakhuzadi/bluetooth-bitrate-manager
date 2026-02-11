#!/usr/bin/env python3
"""
Bluetooth Audio Bitrate Monitor for Linux (PipeWire/PulseAudio)
Displays real-time codec and bitrate information for Bluetooth audio devices.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional, Sequence

from . import bitrate_utils


def get_bt_devices():
    """Get Bluetooth audio devices and their codec info from PipeWire."""
    try:
        result = subprocess.run(['pw-dump'], capture_output=True, text=True)
        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)
        bt_devices = []

        for item in data:
            if item.get('type') != 'PipeWire:Interface:Node':
                continue

            info = item.get('info', {})
            props = info.get('props', {})

            if 'bluez' not in props.get('device.api', ''):
                continue

            device_info = {
                'id': item.get('id'),
                'name': props.get('node.name', 'Unknown'),
                'description': props.get('node.description', 'Unknown'),
                'device_name': props.get('device.name', 'Unknown'),
                'media_class': props.get('media.class', 'Unknown'),
                'codec': 'Unknown',
                'bitrate': 'Unknown',
                'channels': props.get('audio.channels', 'Unknown'),
                'rate': props.get('audio.rate', 'Unknown'),
                'channel_mode': 'Unknown',
                'block_length': 'Unknown',
                'subbands': 'Unknown',
            }

            profile = props.get('device.profile', '')
            if profile:
                device_info['profile'] = profile
                profile_lower = profile.lower()
                if 'sbc' in profile_lower:
                    device_info['codec'] = 'SBC'
                elif 'aac' in profile_lower:
                    device_info['codec'] = 'AAC'
                elif 'aptx' in profile_lower:
                    device_info['codec'] = 'aptX'
                elif 'ldac' in profile_lower:
                    device_info['codec'] = 'LDAC'
                elif 'headset' in profile_lower or 'hfp' in profile_lower:
                    device_info['codec'] = 'mSBC/CVSD'

            bt_devices.append(device_info)

        return bt_devices

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return []


def get_pactl_bt_info():
    """Get Bluetooth info from pactl (more reliable)."""
    try:
        result = subprocess.run(['pactl', 'list', 'sinks'], capture_output=True, text=True)
        if result.returncode != 0:
            return []

        devices = []
        current_device = None

        for line in result.stdout.split('\n'):
            if line.startswith('Sink #'):
                if current_device and current_device.get('is_bluetooth'):
                    devices.append(current_device)
                current_device = {
                    'is_bluetooth': False,
                    'channel_mode': 'Unknown',
                    'block_length': 'Unknown',
                    'subbands': 'Unknown',
                }
            elif current_device is not None:
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
                    codec_lower = codec.lower()
                    current_device['codec_raw'] = codec

                    if 'sbc' in codec_lower:
                        is_xq = 'xq' in codec_lower
                        current_device['codec'] = 'SBC XQ' if is_xq else 'SBC'
                        config = bitrate_utils.fetch_sbc_configuration(current_device.get('address', '')) if current_device.get('address') else None
                        if config:
                            bitrate = bitrate_utils.sbc_bitrate_from_config(config)
                            bitpool = config.effective_bitpool
                            if bitrate and bitpool is not None:
                                formatted = bitrate_utils.format_bitrate(bitrate)
                                current_device['bitrate'] = f'{formatted} (bitpool {bitpool})'
                            else:
                                current_device['bitrate'] = '~552 kbps' if is_xq else '~328 kbps'
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
                            current_device['bitrate'] = '~552 kbps' if is_xq else '~328 kbps'
                    elif 'aac' in codec_lower:
                        current_device['codec'] = 'AAC'
                        current_device['bitrate'] = '~256 kbps'
                    elif 'aptx_hd' in codec_lower:
                        current_device['codec'] = 'aptX HD'
                        current_device['bitrate'] = '576 kbps'
                    elif 'aptx' in codec_lower:
                        current_device['codec'] = 'aptX'
                        current_device['bitrate'] = '352 kbps'
                    elif 'ldac' in codec_lower:
                        current_device['codec'] = 'LDAC'
                        if 'hq' in codec_lower:
                            current_device['bitrate'] = '~990 kbps'
                        elif 'sq' in codec_lower:
                            current_device['bitrate'] = '~660 kbps'
                        else:
                            current_device['bitrate'] = '~330-990 kbps'
                    elif 'msbc' in codec_lower:
                        current_device['codec'] = 'mSBC'
                        current_device['bitrate'] = '~64 kbps'
                    elif 'cvsd' in codec_lower:
                        current_device['codec'] = 'CVSD'
                        current_device['bitrate'] = '~64 kbps'
                    else:
                        current_device['codec'] = codec.upper()
                elif 'Sample Specification:' in line:
                    spec = line.split(':', 1)[1].strip()
                    current_device['spec'] = spec
                    match = re.search(r'(\d+)ch\s+(\d+)Hz', spec)
                    if match:
                        current_device['channels'] = match.group(1)
                        current_device['rate'] = match.group(2)

        if current_device and current_device.get('is_bluetooth'):
            devices.append(current_device)

        return devices

    except Exception as exc:
        print(f"Error getting pactl info: {exc}", file=sys.stderr)
        return []


def format_device_info(device):
    """Format device info for display."""
    lines = [
        f"  Device: {device.get('description', 'Unknown')}",
        f"  Codec:  {device.get('codec', 'Unknown')}",
    ]

    if device.get('bitrate'):
        lines.append(f"  Bitrate: {device.get('bitrate')}")

    if device.get('rate') and device.get('rate') != 'Unknown':
        lines.append(f"  Sample Rate: {device['rate']} Hz")
    if device.get('channels') and device.get('channels') != 'Unknown':
        lines.append(f"  Channels: {device['channels']}")
    if device.get('channel_mode') and device.get('channel_mode') != 'Unknown':
        lines.append(f"  Channel Mode: {device['channel_mode']}")
    block_length = device.get('block_length')
    subbands = device.get('subbands')
    if ((block_length and block_length != 'Unknown') or
            (subbands and subbands != 'Unknown')):
        parts = []
        if block_length and block_length != 'Unknown':
            parts.append(f"{block_length} blocks")
        if subbands and subbands != 'Unknown':
            parts.append(f"{subbands} subbands")
        lines.append(f"  SBC Frame: {' / '.join(parts)}")
    if device.get('codec_raw'):
        lines.append(f"  Raw Codec: {device['codec_raw']}")

    return '\n'.join(lines)


def clear_screen():
    """Clear terminal screen."""
    print('\033[2J\033[H', end='')


def monitor_loop(interval=2):
    """Main monitoring loop."""
    try:
        while True:
            clear_screen()

            print("=" * 60)
            print("  Bluetooth Audio Bitrate Monitor")
            print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            print("=" * 60)
            print()

            devices = get_pactl_bt_info()
            if not devices:
                devices = get_bt_devices()

            if devices:
                for idx, device in enumerate(devices, 1):
                    print(f"[Device {idx}]")
                    print(format_device_info(device))
                    print()
            else:
                print("  No Bluetooth audio devices found")
                print("  Make sure a Bluetooth audio device is connected")

            print("=" * 60)
            print(f"  Refreshing every {interval}s... (Ctrl+C to exit)")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")
        sys.exit(0)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Monitor Bluetooth audio bitrate')
    parser.add_argument('-i', '--interval', type=int, default=2,
                        help='Refresh interval in seconds (default: 2)')
    parser.add_argument('-o', '--once', action='store_true',
                        help='Show info once and exit')
    parser.add_argument('-w', '--watch', action='store_true',
                        help='Continuously watch and refresh output (default behavior)')

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.once:
        devices = get_pactl_bt_info()
        if not devices:
            devices = get_bt_devices()

        if devices:
            for device in devices:
                print(format_device_info(device))
        else:
            print("No Bluetooth audio devices found")
        return 0

    if args.interval < 1:
        print("Interval must be at least 1 second.", file=sys.stderr)
        return 2

    monitor_loop(args.interval)
    return 0


if __name__ == '__main__':
    sys.exit(main())
