import json

from srm import snapshot
from srm.run_monthly import diff_runs, render_log


def test_first_run_is_a_baseline():
    assert "baseline" in diff_runs(None, {"indicators": {}, "regimes": {}})[0]


def test_diff_reports_new_periods_revisions_and_regime_changes():
    prev = {
        "indicators": {
            "a": {"period": "2026-08", "value": 3.3},
            "b": {"period": "2026-Q1", "value": 1.0},
        },
        "regimes": {"hfl": {"position": "supported", "direction": "increasing"}},
    }
    cur = {
        "indicators": {
            "a": {"period": "2026-09", "value": 3.8},
            "b": {"period": "2026-Q1", "value": 1.2},
        },
        "regimes": {"hfl": {"position": "strongly supported", "direction": "increasing"}},
    }
    changes = diff_runs(prev, cur)
    assert any("new period 2026-09" in c for c in changes)
    assert any("revised from 1.0 to 1.2" in c for c in changes)
    assert any("strongly supported" in c for c in changes)


def test_render_log_lists_failures():
    log = {
        "date": "2026-11-05",
        "model_version": "v",
        "tests": "ok",
        "changes": ["x"],
        "regimes": {},
        "indicators": {},
        "pulls": [{"card": "c", "label": "l", "status": "failed", "error": "timeout"}],
    }
    assert "FAILED c/l: timeout" in render_log(log)


class _Resp:
    def __init__(self, body):
        self._b, self.status, self.headers = body, 200, {}

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_unchanged_content_is_not_archived_twice(monkeypatch, tmp_path):
    body = b"KEY,V\nA,1\n"
    monkeypatch.setattr(snapshot.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    first = snapshot.fetch("c", "l", "https://x.example/d", "csv", raw_dir=tmp_path)
    second = snapshot.fetch("c", "l", "https://x.example/d", "csv", raw_dir=tmp_path)
    assert not first.unchanged and second.unchanged
    assert len(list((tmp_path / "c").glob("*.meta.json"))) == 1
    meta = json.loads(first.meta_path.read_text())
    assert meta["sha256"] == second.sha256
