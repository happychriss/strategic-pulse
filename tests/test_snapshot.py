import gzip
import json

import pytest

from srm import snapshot
from srm.snapshot import SnapshotError, _looks_like, _redact, fetch


def test_html_is_not_accepted_as_csv_or_json():
    html = b"<html><head><title>European Central Bank</title>"
    assert not _looks_like("csv", html)
    assert not _looks_like("json", html)
    assert not _looks_like("xml", html)


def test_json_error_and_empty_payloads_are_rejected():
    assert not _looks_like("json", b'{"error": [{"status": 400, "label": "Invalid"}]}')
    assert not _looks_like("json", b'{"version":"2.0","class":"dataset","value":{},"id":["geo"]}')
    assert not _looks_like("json", b'[{"message":[{"id":"175","key":"Invalid format"}]}]')


def test_real_payloads_are_accepted():
    assert _looks_like("csv", b"KEY,FREQ,OBS_VALUE\nA,M,1\n")
    assert _looks_like("json", b'{"version":"2.0"}')
    assert _looks_like("xml", b'<?xml version="1.0"?><a/>')


def test_tokens_are_redacted():
    url = "https://x.example/api?securityToken=SECRET&periodStart=1"
    assert "SECRET" not in _redact(url)
    assert "periodStart=1" in _redact(url)


class _Resp:
    def __init__(self, body: bytes):
        self._body = body
        self.status = 200
        self.headers = {"Content-Type": "text/csv"}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_archives_bytes_and_metadata(monkeypatch, tmp_path):
    body = b"KEY,V\nA,1\n"
    monkeypatch.setattr(snapshot.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    snap = fetch("c1", "lbl", "https://x.example/d?token=SECRET", "csv", raw_dir=tmp_path)
    assert snap.path.read_bytes() == body
    meta = json.loads(snap.meta_path.read_text())
    assert meta["sha256"] == snap.sha256 and "SECRET" not in meta["url"]


def test_large_payload_is_gzipped_losslessly(monkeypatch, tmp_path):
    body = b"KEY,V\n" + b"A,1\n" * 2_000_000
    monkeypatch.setattr(snapshot.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    snap = fetch("c1", "big", "https://x.example/d", "csv", raw_dir=tmp_path)
    assert snap.path.name.endswith(".csv.gz")
    assert gzip.decompress(snap.path.read_bytes()) == body


def test_html_response_is_rejected_after_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(
        snapshot.urllib.request, "urlopen", lambda *a, **k: _Resp(b"<html>x</html>")
    )
    with pytest.raises(SnapshotError):
        fetch("c1", "lbl", "https://x.example/d", "csv", retries=2, raw_dir=tmp_path)
    assert not list(tmp_path.rglob("*.csv"))
