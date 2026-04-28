# RetroWave OPL3 Web UI

A browser-based player for the [SudoMaker RetroWave OPL3 HAT](https://github.com/SudoMaker/RetroWave) on Raspberry Pi. Upload MIDI, VGM, and VGZ files, select an OPL3 instrument bank, and play them through real YMF262-M FM synthesis hardware. Includes a live 18-channel OPL3 visualizer.

```
██████╗ ███████╗████████╗██████╗  ██████╗ ██╗    ██╗ █████╗ ██╗   ██╗███████╗
██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██║    ██║██╔══██╗██║   ██║██╔════╝
██████╔╝█████╗     ██║   ██████╔╝██║   ██║██║ █╗ ██║███████║██║   ██║█████╗
██╔══██╗██╔══╝     ██║   ██╔══██╗██║   ██║██║███╗██║██╔══██║╚██╗ ██╔╝██╔══╝
██║  ██║███████╗   ██║   ██║  ██║╚██████╔╝╚███╔███╔╝██║  ██║ ╚████╔╝ ███████╗
╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═╝  ╚═══╝  ╚══════╝
░░ OPL3 HAT PLAYER ░░ YMF262-M ░░ REAL HARDWARE SYNTHESIS ░░
```

## Hardware Requirements

- Raspberry Pi (tested on Pi 4B)
- [SudoMaker RetroWave OPL3 HAT](https://github.com/SudoMaker/RetroWave) (discontinued; check secondary markets)
- SPI enabled on the Pi (`dtparam=spi=on` in `/boot/firmware/config.txt`)

> **Note on noise:** The RetroWave OPL3 HAT was designed for SudoMaker's "Potato" USB carrier board, which has a much cleaner power domain than a Pi 4. You may hear coil whine or EMI noise on a Pi 4, particularly from the Gigabit Ethernet PHY. A USB WiFi adapter and disabling the onboard Ethernet (`dtoverlay=disable-eth`) can help.

## Software Requirements

- Raspberry Pi OS (Debian Bookworm/Trixie or later)
- Python 3.11+ with Flask 3.x (`sudo apt install python3-flask`)
- [`RetroWave_Player`](https://github.com/SudoMaker/RetroWave) built and installed at `/usr/local/bin/RetroWave_Player`
- [`midi2vgm_opl3`](https://github.com/SudoMaker/RetroWaveMIDIProxy) built at `~/midi2vgm/build/midi2vgm_opl3` (for MIDI support)
- `gzip` (standard, for VGZ decompression)

## Installation

```bash
git clone https://github.com/Raikiri1310/Retrowave_UI.git ~/retrowave-ui
mkdir -p ~/midi ~/vgm/scratch
```

### Run manually

```bash
python3 ~/retrowave-ui/app.py
```

Open `http://<pi-ip>:8765` in a browser on your LAN.

### Run as a systemd service

```bash
sudo cp ~/retrowave-ui/retrowave-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now retrowave-ui
```

The service file assumes the app lives at `~/retrowave-ui/` and runs as user `zaraki`. Edit `User=` to match your username.

## Configuration

All paths can be overridden with environment variables:

| Variable | Default | Description |
|---|---|---|
| `RW_MIDI_DIR` | `~/midi` | MIDI file library |
| `RW_VGM_DIR` | `~/vgm` | VGM/VGZ file library |
| `RW_SCRATCH` | `~/vgm/scratch` | Temp dir for conversions |
| `RW_MIDI2VGM` | `~/midi2vgm/build/midi2vgm_opl3` | Path to midi2vgm_opl3 binary |
| `RW_PLAYER` | `/usr/local/bin/RetroWave_Player` | Path to RetroWave_Player binary |

## Features

- Upload `.mid`, `.vgm`, `.vgz`, or `.zip` files from the browser (drag and drop supported)
- 70+ OPL3 instrument banks for MIDI conversion via `midi2vgm_opl3`
- Bank selector automatically grays out for VGM/VGZ files (bank is embedded in the recording)
- Live 18-channel OPL3 register visualizer — parses the VGM data and shows each voice activating in real time
- OPL2 VGMs light up channels 1-9; OPL3 VGMs can use all 18
- Clean chip shutdown on stop — sends key-off and max attenuation to all registers so the chip goes quiet immediately
- Status polling every 2 seconds detects when a track finishes

## File Sources

Good places to find OPL3 VGM/VGZ files:

- [vgmrips.net](https://vgmrips.net) — filter by chip **YMF262** for OPL3, **YM3812** for OPL2
- Good packs to start with: *Doom*, *Doom II*, *Jazz Jackrabbit*, *Wolfenstein 3D*, *Rise of the Triad*

For MIDI: any standard MIDI file works. GM-compatible banks (e.g. bank 65 — SB Modded GMOPL) sound best with standard GM MIDIs. Non-GM banks are labeled in the dropdown.

## Project Structure

```
app.py              — Flask app, all routes
vgm_parser.py       — VGM file parser and OPL3 channel visualizer data
templates/
    index.html      — Single-page UI (vanilla JS, no framework)
static/
    style.css       — Phosphor green demoscene aesthetic
tests/
    test_app.py     — pytest suite (19 tests)
retrowave-ui.service — systemd unit file
```

## Running Tests

```bash
pip install flask pytest
pytest tests/
```

## License

MIT — see [LICENSE](LICENSE).
