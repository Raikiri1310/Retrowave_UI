import struct
from pathlib import Path

SAMPLE_RATE = 44100
SNAPSHOT_INTERVAL = 2205  # 50ms at 44100Hz

# Carrier operator register offsets for OPL3 channels 0-8
# (added to 0x40 base to get TL register)
_CARRIER_OFFSETS = [0x03, 0x04, 0x05, 0x0B, 0x0C, 0x0D, 0x13, 0x14, 0x15]

# Bytes to skip (beyond the command byte) for commands we don't handle
_CMD_SKIP = {}
for c in range(0x30, 0x40): _CMD_SKIP[c] = 1
for c in range(0x40, 0x51): _CMD_SKIP[c] = 1  # 0x5A handled above
for c in range(0x51, 0x5E): _CMD_SKIP[c] = 2  # various 2-byte chip writes
for c in range(0x68, 0x70): _CMD_SKIP[c] = 1
for c in range(0xA0, 0xC0): _CMD_SKIP[c] = 2
for c in range(0xC0, 0xE0): _CMD_SKIP[c] = 3
for c in range(0xE0, 0x100): _CMD_SKIP[c] = 4


def parse_vgm(path):
    """Parse a VGM file and return a list of channel-state snapshots at 50ms intervals."""
    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < 0x40 or data[0:4] != b'Vgm ':
        return []

    data_off_rel = struct.unpack_from('<I', data, 0x34)[0]
    pos = (0x34 + data_off_rel) if data_off_rel else 0x40

    # Two ports × 256 registers
    regs = [[0] * 256, [0] * 256]
    samples = 0
    next_snap = 0
    snapshots = []

    while pos < len(data):
        cmd = data[pos]

        if cmd in (0x5E, 0x5A):   # OPL3 port 0 / OPL2
            regs[0][data[pos + 1]] = data[pos + 2]
            pos += 3
        elif cmd == 0x5F:          # OPL3 port 1
            regs[1][data[pos + 1]] = data[pos + 2]
            pos += 3
        elif cmd == 0x61:
            samples += struct.unpack_from('<H', data, pos + 1)[0]
            pos += 3
        elif cmd == 0x62:
            samples += 735
            pos += 1
        elif cmd == 0x63:
            samples += 882
            pos += 1
        elif cmd == 0x66:
            break
        elif 0x70 <= cmd <= 0x7F:
            samples += (cmd & 0x0F) + 1
            pos += 1
        elif 0x80 <= cmd <= 0x8F:
            samples += cmd & 0x0F
            pos += 1
        elif cmd == 0x67:
            # Data block: 0x67 0x66 tt ss[4] data[ss]
            size = struct.unpack_from('<I', data, pos + 3)[0]
            pos += 7 + size
        elif cmd in _CMD_SKIP:
            pos += 1 + _CMD_SKIP[cmd]
        else:
            pos += 1

        while samples >= next_snap:
            snapshots.append(_snapshot(regs))
            next_snap += SNAPSHOT_INTERVAL

    snapshots.append(_snapshot(regs))
    return snapshots


def _snapshot(regs):
    channels = []
    for port in range(2):
        for ch in range(9):
            b = regs[port][0xB0 + ch]
            key_on = bool(b & 0x20)
            block = (b >> 2) & 0x07
            tl = regs[port][0x40 + _CARRIER_OFFSETS[ch]] & 0x3F
            vol = (63 - tl) if key_on else 0
            channels.append([int(key_on), int(block), int(vol)])
    return channels


def make_reset_vgm(dest: Path):
    """Write a minimal VGM that silences all OPL3 channels and operators."""
    cmds = bytearray()

    # Key-off all 18 channels (port 0 = OPL3/OPL2, port 1 = OPL3 only)
    for port_cmd in (0x5E, 0x5F):
        for ch in range(9):
            cmds += bytes([port_cmd, 0xB0 + ch, 0x00])

    # Max attenuation on all 18 operator slots per port (regs 0x40-0x55)
    for port_cmd in (0x5E, 0x5F):
        for reg in range(0x40, 0x56):
            cmds += bytes([port_cmd, reg, 0x3F])

    cmds += bytes([0x66])  # end of data

    # VGM 1.51 header — 0x80 bytes so YMF262 clock at 0x5C fits inside
    header = bytearray(0x80)
    header[0:4] = b'Vgm '
    total = 0x80 + len(cmds)
    struct.pack_into('<I', header, 0x04, total - 4)       # EOF offset (rel to 0x04)
    struct.pack_into('<I', header, 0x08, 0x00000151)      # version 1.51
    struct.pack_into('<I', header, 0x34, 0x0000004C)      # data offset rel to 0x34 → 0x80
    struct.pack_into('<I', header, 0x5C, 14318180)        # YMF262 clock

    dest.write_bytes(bytes(header) + bytes(cmds))
    return dest
