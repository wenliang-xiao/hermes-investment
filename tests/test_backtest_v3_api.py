"""backtest_v3 API — WS4: /api/v2/backtest/v3/* 端点契约测试.

list/run/detail/report 四个端点。run 用 monkeypatch stub 掉真实回测引擎
(不跑 baostock/quantstats, 保证测试快且不碰真实报告目录)。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def v3_meta():
    return {
        "run_id": "faceji_20260819_120000",
        "strategy": "faceji",
        "run_date": "2026-08-19T12:00:00",
        "params": {"days": 120, "capital": 1000000},
        "metrics": {"sharpe": 1.98, "sortino": 3.09, "cagr": 41.11,
                    "max_drawdown": -5.9, "win_rate": 54.63, "n_days": 108},
        "report_file": "report.html",
        "n_trades": 23,
        "n_days": 109,
    }


class TestV3List:
    def test_list_endpoint_returns_reports(self, monkeypatch, v3_meta):
        """GET /api/v2/backtest/v3/list → {count, reports:[meta]}"""
        from dashboard import api_backtest
        monkeypatch.setattr(
            "engine.backtest_v3.list_reports",
            lambda: [v3_meta, dict(v3_meta, run_id="silverquant_1")],
        )
        out = api_backtest.api_v2_backtest_v3_list()
        assert out["count"] == 2
        assert out["reports"][0]["run_id"] == "faceji_20260819_120000"
        assert "metrics" in out["reports"][0]

    def test_list_empty(self, monkeypatch):
        """无报告时 count=0, reports=[] 不崩."""
        from dashboard import api_backtest
        monkeypatch.setattr("engine.backtest_v3.list_reports", lambda: [])
        out = api_backtest.api_v2_backtest_v3_list()
        assert out == {"count": 0, "reports": []}


class TestV3Run:
    def test_run_endpoint_returns_report_url(self, monkeypatch, v3_meta):
        """GET /api/v2/backtest/v3/run → run_backtest_v3 结果 + report_url"""
        from dashboard import api_backtest
        fake = dict(v3_meta)
        fake["report_path"] = "/tmp/fake/report.html"

        def _fake_run(strategy, days, capital, custom_symbols, benchmark, run_id):
            assert strategy == "faceji"
            assert days == 120
            assert custom_symbols == ["000001", "600519"]
            assert benchmark is True
            return dict(fake, run_id=run_id or "faceji_auto")

        monkeypatch.setattr("engine.backtest_v3.run_backtest_v3", _fake_run)
        out = api_backtest.api_v2_backtest_v3_run(
            strategy="faceji", days=120, capital=1000000,
            symbols="000001,600519", benchmark=True,
            run_id="faceji_20260819_120000",
        )
        assert out["run_id"] == "faceji_20260819_120000"
        assert out["report_url"] == "/api/v2/backtest/v3/report/faceji_20260819_120000"
        assert out["metrics"]["sharpe"] == 1.98

    def test_run_error_propagates(self, monkeypatch):
        """引擎返回 {'error': ...} → 端点透传 error, 不抛异常."""
        from dashboard import api_backtest
        monkeypatch.setattr(
            "engine.backtest_v3.run_backtest_v3",
            lambda **kw: {"error": "净值曲线过短(3天)"},
        )
        out = api_backtest.api_v2_backtest_v3_run(strategy="faceji")
        assert "error" in out


class TestV3Detail:
    def test_detail_endpoint(self, monkeypatch, v3_meta):
        """GET /api/v2/backtest/v3/{run_id} → meta + report_url"""
        from dashboard import api_backtest
        monkeypatch.setattr(
            "engine.backtest_v3.get_report",
            lambda rid: dict(v3_meta, report_path="/tmp/fake/report.html"),
        )
        out = api_backtest.api_v2_backtest_v3_detail("faceji_20260819_120000")
        assert out["run_id"] == "faceji_20260819_120000"
        assert out["report_url"] == "/api/v2/backtest/v3/report/faceji_20260819_120000"

    def test_detail_not_found(self, monkeypatch):
        """run_id 不存在 → {'error': ...}"""
        from dashboard import api_backtest
        monkeypatch.setattr("engine.backtest_v3.get_report", lambda rid: None)
        out = api_backtest.api_v2_backtest_v3_detail("nope")
        assert "error" in out


class TestV3ReportServing:
    def test_report_endpoint_serves_html(self, monkeypatch, tmp_path):
        """GET /api/v2/backtest/v3/report/{run_id} → 200 text/html 报告内容"""
        from dashboard import api_backtest
        import engine.backtest_v3 as bv3
        # 隔离到 tmp 目录, 不碰真实报告
        monkeypatch.setattr(bv3, "REPORT_ROOT", tmp_path)
        report_file = tmp_path / "faceji_x" / "report.html"
        report_file.parent.mkdir(parents=True)
        report_file.write_text("<html><body>quantstats faceji report</body></html>")
        resp = api_backtest.api_v2_backtest_v3_report("faceji_x")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/html")
        assert "quantstats faceji report" in resp.body.decode()

    def test_report_endpoint_missing(self, monkeypatch, tmp_path):
        """报告缺失 → 404 HTML 提示."""
        from dashboard import api_backtest
        import engine.backtest_v3 as bv3
        monkeypatch.setattr(bv3, "REPORT_ROOT", tmp_path)
        resp = api_backtest.api_v2_backtest_v3_report("missing_run")
        assert resp.status_code == 404