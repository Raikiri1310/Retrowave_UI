import io
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from vgm_parser import make_reset_vgm, parse_vgm

app = Flask(__name__)

MIDI_DIR = Path(os.environ.get('RW_MIDI_DIR', str(Path.home() / 'midi')))
VGM_DIR  = Path(os.environ.get('RW_VGM_DIR',  str(Path.home() / 'vgm')))
SCRATCH  = Path(os.environ.get('RW_SCRATCH',  str(Path.home() / 'vgm' / 'scratch')))
MIDI2VGM = os.environ.get('RW_MIDI2VGM', str(Path.home() / 'midi2vgm' / 'build' / 'midi2vgm_opl3'))
PLAYER   = os.environ.get('RW_PLAYER',   '/usr/local/bin/RetroWave_Player')
PLAYER_ARGS = ['-t', 'spi', '-d', '/dev/spidev0.0', '-g', '0,6']

state = {'track': None, 'type': None, 'bank': None, 'snapshots': [], 'play_start': None}
banks = []
RESET_VGM = Path(__file__).parent / 'reset.vgm'


def _reset_chip():
    """Kill player and send silence to all OPL3 registers."""
    subprocess.run(['pkill', '-f', 'RetroWave_Player'], capture_output=True)
    if RESET_VGM.exists():
        subprocess.run([PLAYER] + PLAYER_ARGS + [str(RESET_VGM)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _load_banks():
    global banks
    try:
        result = subprocess.run([MIDI2VGM, '--show-banks'], capture_output=True, text=True, timeout=10)
        banks = _parse_banks(result.stdout)
    except Exception:
        banks = []


def _parse_banks(output):
    result = []
    for line in output.splitlines():
        m = re.match(r'^\s*(\d+)\s*[-–]\s*(.+)', line.strip())
        if m:
            result.append({'id': int(m.group(1)), 'name': m.group(2).strip()})
    return result


def _is_playing():
    r = subprocess.run(['pgrep', '-f', 'RetroWave_Player'], capture_output=True)
    return r.returncode == 0


def _list_files():
    files = []
    for f in sorted(MIDI_DIR.rglob('*')):
        if f.suffix.lower() in ('.mid', '.midi') and f.is_file():
            files.append({'name': f.name, 'type': 'midi'})
    for f in sorted(VGM_DIR.rglob('*')):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if f.is_relative_to(SCRATCH):
            continue
        if ext == '.vgm':
            files.append({'name': f.name, 'type': 'vgm'})
        elif ext == '.vgz':
            files.append({'name': f.name, 'type': 'vgz'})
    return files


def _find_file(filename):
    for f in MIDI_DIR.rglob(filename):
        if f.is_file():
            return f
    for f in VGM_DIR.rglob(filename):
        if f.is_file() and not f.is_relative_to(SCRATCH):
            return f
    return None


@app.route('/')
def index():
    return render_template('index.html', banks=banks, files=_list_files())


@app.route('/api/files')
def api_files():
    return jsonify(_list_files())


@app.route('/api/status')
def api_status():
    playing = _is_playing()
    if not playing:
        state['track'] = None
        state['type'] = None
        state['bank'] = None
    return jsonify({
        'playing': playing,
        'track': state['track'],
        'type': state['type'],
        'bank': state['bank'],
    })


@app.route('/play', methods=['POST'])
def play():
    data = request.get_json(force=True)
    filename = data.get('file', '').strip()
    bank = data.get('bank', 0)

    if not filename:
        return jsonify({'error': 'no file specified'}), 400

    filepath = _find_file(filename)
    if filepath is None:
        return jsonify({'error': 'file not found'}), 404

    _reset_chip()

    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    ext = filepath.suffix.lower()
    vgm_path = None
    file_type = None

    if ext in ('.mid', '.midi'):
        file_type = 'midi'
        out_vgm = SCRATCH / 'out.vgm'
        r = subprocess.run(
            [MIDI2VGM, '--bank', str(bank), '--in', str(filepath), '--out', str(out_vgm)],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            return jsonify({'error': 'conversion failed', 'detail': r.stderr}), 500
        vgm_path = out_vgm

    elif ext == '.vgz':
        file_type = 'vgz'
        out_vgm = SCRATCH / 'out.vgm'
        with open(out_vgm, 'wb') as outf:
            r = subprocess.run(['gzip', '-cd', str(filepath)], stdout=outf, capture_output=False)
        if r.returncode != 0:
            return jsonify({'error': 'decompression failed'}), 500
        vgm_path = out_vgm

    elif ext == '.vgm':
        file_type = 'vgm'
        vgm_path = filepath

    else:
        return jsonify({'error': 'unsupported file type'}), 400

    try:
        state['snapshots'] = parse_vgm(str(vgm_path))
    except Exception:
        state['snapshots'] = []

    subprocess.Popen(
        [PLAYER] + PLAYER_ARGS + [str(vgm_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    state['track'] = filename
    state['type'] = file_type
    state['bank'] = bank if file_type == 'midi' else None
    state['play_start'] = time.time()

    return jsonify({'ok': True})


@app.route('/api/visualizer')
def visualizer():
    _EMPTY = json.dumps([[0, 0, 0]] * 18)

    def generate():
        try:
            while True:
                snapshots = state['snapshots']
                play_start = state['play_start']
                if snapshots and play_start and _is_playing():
                    elapsed_ms = int((time.time() - play_start) * 1000)
                    idx = min(elapsed_ms // 50, len(snapshots) - 1)
                    yield f'data: {json.dumps(snapshots[idx])}\n\n'
                else:
                    yield f'data: {_EMPTY}\n\n'
                time.sleep(0.05)
        except GeneratorExit:
            pass

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/stop', methods=['POST'])
def stop():
    _reset_chip()
    state['track'] = None
    state['type'] = None
    state['bank'] = None
    state['snapshots'] = []
    state['play_start'] = None
    return jsonify({'ok': True})


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400

    f = request.files['file']
    name = f.filename or ''
    ext = Path(name).suffix.lower()

    MIDI_DIR.mkdir(parents=True, exist_ok=True)
    VGM_DIR.mkdir(parents=True, exist_ok=True)

    if ext in ('.mid', '.midi'):
        f.save(MIDI_DIR / Path(name).name)
        return jsonify({'ok': True})

    elif ext == '.vgm':
        f.save(VGM_DIR / Path(name).name)
        return jsonify({'ok': True})

    elif ext == '.vgz':
        f.save(VGM_DIR / Path(name).name)
        return jsonify({'ok': True})

    elif ext == '.zip':
        try:
            with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
                for member in zf.namelist():
                    mext = Path(member).suffix.lower()
                    if mext in ('.mid', '.midi'):
                        (MIDI_DIR / Path(member).name).write_bytes(zf.read(member))
                    elif mext in ('.vgm', '.vgz'):
                        (VGM_DIR / Path(member).name).write_bytes(zf.read(member))
        except zipfile.BadZipFile:
            return jsonify({'error': 'bad zip file'}), 400
        return jsonify({'ok': True})

    else:
        return jsonify({'error': f'unsupported file type: {ext}'}), 400


@app.route('/file/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    filepath = _find_file(filename)
    if filepath is None:
        return jsonify({'error': 'not found'}), 404
    filepath.unlink()
    return jsonify({'ok': True})


if __name__ == '__main__':
    make_reset_vgm(RESET_VGM)
    _load_banks()
    app.run(host='0.0.0.0', port=8765, debug=False, threaded=True)
