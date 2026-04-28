import importlib
import io
import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


BANK_OUTPUT = """\
  0 - 2OP ADLIB (Default OPL2 GM set)
 14 - DMX (Doom 2)
 43 - AIL (Warcraft) :NON-GM:
 58 - OP3 (The Fat Man 2op set; Win9x)
 65 - SB (Modded GMOPL by Wohlstand)
"""


@pytest.fixture(autouse=True)
def app_module(tmp_path, monkeypatch):
    midi_dir = tmp_path / 'midi'
    vgm_dir  = tmp_path / 'vgm'
    scratch  = tmp_path / 'vgm' / 'scratch'
    midi_dir.mkdir()
    vgm_dir.mkdir()
    scratch.mkdir()

    monkeypatch.setenv('RW_MIDI_DIR',  str(midi_dir))
    monkeypatch.setenv('RW_VGM_DIR',   str(vgm_dir))
    monkeypatch.setenv('RW_SCRATCH',   str(scratch))
    monkeypatch.setenv('RW_MIDI2VGM',  '/fake/midi2vgm_opl3')
    monkeypatch.setenv('RW_PLAYER',    '/fake/RetroWave_Player')

    if 'app' in sys.modules:
        del sys.modules['app']

    # Resolve app.py path relative to this test file
    app_path = Path(__file__).parent.parent / 'app.py'
    spec = importlib.util.spec_from_file_location('app', app_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['app'] = module
    spec.loader.exec_module(module)

    yield module

    del sys.modules['app']


@pytest.fixture()
def client(app_module):
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


# ── Bank parser ──────────────────────────────────────────────────────────────

def test_parse_banks_count(app_module):
    result = app_module._parse_banks(BANK_OUTPUT)
    assert len(result) == 5


def test_parse_banks_fields(app_module):
    result = app_module._parse_banks(BANK_OUTPUT)
    assert result[0] == {'id': 0, 'name': '2OP ADLIB (Default OPL2 GM set)'}
    assert result[3] == {'id': 58, 'name': 'OP3 (The Fat Man 2op set; Win9x)'}


# ── /api/status ───────────────────────────────────────────────────────────────

def test_status_not_playing(client, app_module):
    with patch.object(app_module.subprocess, 'run') as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        r = client.get('/api/status')
    assert r.status_code == 200
    data = r.get_json()
    assert data['playing'] is False
    assert data['track'] is None


def test_status_playing(client, app_module):
    app_module.state['track'] = 'test.mid'
    app_module.state['type'] = 'midi'
    app_module.state['bank'] = 58
    with patch.object(app_module.subprocess, 'run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        r = client.get('/api/status')
    data = r.get_json()
    assert data['playing'] is True
    assert data['track'] == 'test.mid'
    assert data['bank'] == 58


def test_status_clears_state_when_stopped(client, app_module):
    app_module.state['track'] = 'old.mid'
    app_module.state['type'] = 'midi'
    app_module.state['bank'] = 14
    with patch.object(app_module.subprocess, 'run') as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        r = client.get('/api/status')
    data = r.get_json()
    assert data['playing'] is False
    assert data['track'] is None


# ── /play ─────────────────────────────────────────────────────────────────────

def test_play_midi_ok(client, app_module):
    midi_file = Path(app_module.MIDI_DIR) / 'test.mid'
    midi_file.write_bytes(b'\x00' * 16)

    with patch.object(app_module.subprocess, 'run') as mock_run, \
         patch.object(app_module.subprocess, 'Popen') as mock_popen:
        mock_run.return_value = MagicMock(returncode=0, stderr='')
        r = client.post('/play', json={'file': 'test.mid', 'bank': 58})

    assert r.status_code == 200
    assert r.get_json()['ok'] is True
    assert app_module.state['track'] == 'test.mid'
    assert app_module.state['type'] == 'midi'
    assert app_module.state['bank'] == 58


def test_play_vgm_ok(client, app_module):
    vgm_file = Path(app_module.VGM_DIR) / 'test.vgm'
    vgm_file.write_bytes(b'\x00' * 16)

    with patch.object(app_module.subprocess, 'run') as mock_run, \
         patch.object(app_module.subprocess, 'Popen') as mock_popen:
        mock_run.return_value = MagicMock(returncode=0)
        r = client.post('/play', json={'file': 'test.vgm', 'bank': 0})

    assert r.status_code == 200
    assert app_module.state['type'] == 'vgm'
    assert app_module.state['bank'] is None


def test_play_missing_file(client, app_module):
    r = client.post('/play', json={'file': 'ghost.mid', 'bank': 0})
    assert r.status_code == 404


def test_play_midi_conversion_failure(client, app_module):
    midi_file = Path(app_module.MIDI_DIR) / 'bad.mid'
    midi_file.write_bytes(b'\x00' * 16)

    with patch.object(app_module.subprocess, 'run') as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr='conversion error')
        r = client.post('/play', json={'file': 'bad.mid', 'bank': 0})

    assert r.status_code == 500
    assert 'conversion failed' in r.get_json()['error']


def test_play_no_file_specified(client, app_module):
    r = client.post('/play', json={})
    assert r.status_code == 400


# ── /stop ─────────────────────────────────────────────────────────────────────

def test_stop_ok(client, app_module):
    app_module.state['track'] = 'test.mid'
    app_module.state['type'] = 'midi'
    app_module.state['bank'] = 58

    with patch.object(app_module.subprocess, 'run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        r = client.post('/stop')

    assert r.status_code == 200
    assert r.get_json()['ok'] is True
    assert app_module.state['track'] is None


def test_stop_clears_state(client, app_module):
    app_module.state['track'] = 'playing.vgm'
    app_module.state['type'] = 'vgm'
    app_module.state['bank'] = None

    with patch.object(app_module.subprocess, 'run') as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        r = client.post('/stop')

    assert app_module.state['track'] is None
    assert app_module.state['type'] is None


# ── /upload ───────────────────────────────────────────────────────────────────

def test_upload_midi(client, app_module):
    data = {'file': (io.BytesIO(b'\x00' * 16), 'song.mid')}
    r = client.post('/upload', data=data, content_type='multipart/form-data')
    assert r.status_code == 200
    assert (Path(app_module.MIDI_DIR) / 'song.mid').exists()


def test_upload_vgm(client, app_module):
    data = {'file': (io.BytesIO(b'\x00' * 16), 'track.vgm')}
    r = client.post('/upload', data=data, content_type='multipart/form-data')
    assert r.status_code == 200
    assert (Path(app_module.VGM_DIR) / 'track.vgm').exists()


def test_upload_zip_extracts_valid_files(client, app_module):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('cool.mid', b'\x00' * 16)
        zf.writestr('ignore.txt', b'ignored')
        zf.writestr('music.vgz', b'\x00' * 8)
    buf.seek(0)
    data = {'file': (buf, 'pack.zip')}
    r = client.post('/upload', data=data, content_type='multipart/form-data')
    assert r.status_code == 200
    assert (Path(app_module.MIDI_DIR) / 'cool.mid').exists()
    assert (Path(app_module.VGM_DIR) / 'music.vgz').exists()
    assert not (Path(app_module.VGM_DIR) / 'ignore.txt').exists()


def test_upload_unsupported_extension(client, app_module):
    data = {'file': (io.BytesIO(b'\x00'), 'readme.txt')}
    r = client.post('/upload', data=data, content_type='multipart/form-data')
    assert r.status_code == 400


# ── DELETE /file/<filename> ───────────────────────────────────────────────────

def test_delete_midi_file(client, app_module):
    f = Path(app_module.MIDI_DIR) / 'del.mid'
    f.write_bytes(b'\x00')
    r = client.delete('/file/del.mid')
    assert r.status_code == 200
    assert not f.exists()


def test_delete_vgm_file(client, app_module):
    f = Path(app_module.VGM_DIR) / 'del.vgm'
    f.write_bytes(b'\x00')
    r = client.delete('/file/del.vgm')
    assert r.status_code == 200
    assert not f.exists()


def test_delete_not_found(client, app_module):
    r = client.delete('/file/ghost.mid')
    assert r.status_code == 404
