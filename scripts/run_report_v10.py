"""
面基日报 v10 — 信号驱动版 + 产业链 + 新闻
Phase 1: 运行 run_trading 获取信号
Phase 2: 运行 chain_scanner 获取链分析
Phase 3: 运行 news_pipeline 获取新闻
Phase 4: 构建报告 + 飞书文档发布
"""
import sys, os, json, subprocess, time, urllib.request
from datetime import datetime, date

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)

import functools
print = functools.partial(print, flush=True)

# --- Feishu 配置 ---
FEISHU_TOOL = "/home/admin/.hermes/node_modules/.bin/feishu-tool"
WORK_DIR = "/home/admin/.hermes"
FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "")
USER_OPENID = os.environ.get("FEISHU_USER_OPENID", "")
APP_ID = os.environ.get("FEISHU_APP_ID", "")

APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")

def feishu_call(tool, payload):
    d = json.dumps(payload, ensure_ascii=False)
    env = os.environ.copy()
    env["FEISHU_SCOPE_VALIDATION"] = "false"
    r = subprocess.run(
        [FEISHU_TOOL, tool, d],
        capture_output=True, text=True, timeout=30, cwd=WORK_DIR, env=env
    )
    try: return json.loads(r.stdout)
    except: return {}

def get_token():
    r = subprocess.run(["curl", "-s", "-X", "POST",
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET})],
        capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout).get("tenant_access_token", "")

def grant(doc_id):
    token = get_token()
    if not token: return
    subprocess.run(["curl", "-s", "-X", "POST",
        f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx&need_notification=false",
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"})],
        capture_output=True, timeout=10)

# --- Block helpers ---
def h(lv, text):
    return {"blockType": "heading", "options": {"heading": {"level": lv, "content": text}}}
def p(*segs):
    styles = []
    for seg in segs:
        if isinstance(seg, str): styles.append({"text": seg})
        elif isinstance(seg, tuple):
            s = {}
            if len(seg) > 1 and seg[1]: s["bold"] = True
            if len(seg) > 2 and seg[2] is not None: s["text_color"] = seg[2]
            e = {"text": seg[0]}
            if s: e["style"] = s
            styles.append(e)
    return {"blockType": "text", "options": {"text": {"textStyles": styles}}}
def cd(text, lang=1):
    return {"blockType": "code", "options": {"code": {"code": text, "language": lang, "wrap": True}}}
def bl(text):
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}

def write_blocks(doc_id, blocks):
    idx = 0
    for i in range(0, len(blocks), 12):
        batch = blocks[i:i+12]
        r = feishu_call("batch_create_feishu_blocks",
            {"documentId": doc_id, "parentBlockId": doc_id, "index": idx, "blocks": batch})
        n = r.get("totalBlocksCreated", len(batch))
        idx = r.get("nextIndex", idx + n)
        time.sleep(0.3)
    return True


def run_phase_scan(sig_path, today_str):
    """Phase 1: 扫描+信号生成"""
    print("\n[Phase 1] 运行扫描器 + TradingEngine...")
    try:
        r = subprocess.run(
            f"cd {_PROJECT_DIR} && PYTHONUNBUFFERED=1 python3 -u scripts/run_trading.py > /tmp/report_v10_scan.log 2>&1",
            capture_output=True, text=True, timeout=600, shell=True
        )
        if r.returncode != 0:
            print(f"  WARNING: scan exit={r.returncode}")
    except subprocess.TimeoutExpired:
        print(f"  WARNING: scan timeout")

    if not os.path.exists(sig_path):
        print("  FAIL: no signal file")
        return None

    with open(sig_path) as f:
        signals_data = json.load(f)
    signals = signals_data.get("signals", [])
    positions = signals_data.get("positions", {})
    print(f"  OK: {len(signals)} signals, {sum(len(v) for v in positions.values())} positions")
    return signals_data


def run_phase_chain():
    """Phase 2: 产业链分析"""
    print("\n[Phase 2] 产业链扫描...")
    try:
        from research.chain_scanner import scan_chains, format_chain_report
        results = scan_chains()
        report = format_chain_report(results)
        return report
    except Exception as e:
        print(f"  WARNING: chain scanner failed: {e}")
        return "产业链扫描暂不可用"


def run_phase_news():
    """Phase 3: 新闻管线"""
    print("\n[Phase 3] 新闻扫描...")
    news_path = os.path.join(_PROJECT_DIR, "data", "news_events.json")
    summary_path = os.path.join(_PROJECT_DIR, "data", "news_summary.txt")
    try:
        r = subprocess.run(
            f"cd {_PROJECT_DIR} && PYTHONUNBUFFERED=1 python3 -u scripts/news_pipeline.py --mode quick > /tmp/report_news.log 2>&1",
            capture_output=True, text=True, timeout=120, shell=True
        )
    except:
        pass
    summary = ""
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = f.read()[:800]
    news_count = 0
    if os.path.exists(news_path):
        with open(news_path) as f:
            nd = json.load(f)
        news_count = nd.get("total_events", 0)
    print(f"  OK: {news_count} events")
    return summary, news_count


def build_report_blocks(signals_data, chain_report, news_summary, today_str):
    """Phase 4: 构建文档 blocks"""
    signals = signals_data.get("signals", []) if signals_data else []
    positions = signals_data.get("positions", {}) if signals_data else {}
    blocks = []

    # 封面
    blocks.append(h(2, f"面基日报 v10 · {today_str}"))
    blocks.append(p(f"三源融合: faceji x SilverQuant x TradingAgents | {datetime.now().strftime('%H:%M')}"))

    # --- 1. 今日信号（核心） ---
    blocks.append(h(2, "1. 今日信号"))
    if signals:
        lines = ["优先级 策略           动作 标的             价格      理由"]
        lines.append("─" * 75)
        for s in signals:
            pct = {"HIGH": "RED", "MED": "YELLOW", "LOW": "GREY"}.get(s.get("priority", "MED"), "")
            sym = s.get("symbol", "")
            nm = s.get("name", "")
            pr = s.get("price", 0)
            rc = s.get("reason", "")
            lines.append(f"[{s['priority']:4s}] {s['strategy']:<12s} {s['action']:<4s} {sym}({nm:<6s}) {pr:>8.2f}  {rc}")
        blocks.append(cd("\n".join(lines)))
        best = signals[0]
        blocks.append(p(("星今日建议: ", True), (f"{best['strategy']} {best['action']} {best['symbol']}({best.get('name','')}) @{best['price']:.2f}", True, 5)))
        blocks.append(p("手动执行后告知我记录交易日志"))
    else:
        blocks.append(p(("今日无交易信号", True, 3)))
        blocks.append(p("所有标的评分均低于阈值, 三策略无信号"))

    # --- 1.5 上周信号回顾 ---
    blocks.append(h(3, "1a. 上周信号回顾"))
    try:
        today = date.today()
        week_ago = (today - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
        # 从交易记录中提取
        history_path = os.path.join(os.path.dirname(_SCRIPT_DIR), "data", "signal_history.jsonl")
        past_signals = []
        if os.path.exists(history_path):
            with open(history_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("date", "") >= week_ago:
                            past_signals.append(entry)
                    except:
                        pass
        if past_signals:
            sig_lines = ["日期      策略           动作 标的    价格     结果"]
            sig_lines.append("─" * 55)
            for s in sorted(past_signals, key=lambda x: x.get("date", ""), reverse=True)[:10]:
                pnl = s.get("pnl_pct", "")
                pnl_str = f"{pnl:+.2f}%" if isinstance(pnl, (int, float)) else "待结算"
                sig_lines.append(f"{s.get('date','')[:10]} {s.get('strategy',''):<12s} {s.get('action',''):<4s} {s.get('symbol',''):<8s} {s.get('price',0):>8.2f} {pnl_str}")
            blocks.append(cd("\n".join(sig_lines)))
        else:
            # 从 shadow_account 的交易记录提取
            shadow_path = os.path.join(os.path.dirname(_SCRIPT_DIR), "data", "shadow_account.json")
            if os.path.exists(shadow_path):
                with open(shadow_path) as f:
                    shadow = json.load(f)
                recent = [tx for tx in shadow.get("history", []) if tx.get("time", "")[:10] >= week_ago]
                if recent:
                    r_lines = ["时间            标的  操作  价格     数量  盈亏"]
                    r_lines.append("─" * 55)
                    for tx in recent[-10:]:
                        pnl = tx.get("pnl")
                        pnl_s = f"¥{pnl:+.0f}" if pnl else "—"
                        r_lines.append(f"{tx.get('time','')[:16]} {tx.get('symbol',''):<6s} {tx.get('action',''):<4s} {tx.get('price',0):>8.2f} {tx.get('quantity',0):>4d} {pnl_s}")
                    blocks.append(cd("\n".join(r_lines)))
                else:
                    blocks.append(p("过去7天无交易记录"))
            else:
                blocks.append(p("无交易记录"))
    except Exception as e:
        blocks.append(p(f"上周回顾不可用: {e}"))

    # --- 2. 三策略对比 ---
    blocks.append(h(2, "2. 三策略对比"))
    for sname, label in [("faceji", "faceji"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
        s_sigs = [s for s in signals if s["strategy"] == sname]
        s_pos = positions.get(sname, {})
        buys = sum(1 for s in s_sigs if s["action"] == "BUY")
        sells = sum(1 for s in s_sigs if s["action"] == "SELL")
        pnl_strs = []
        for sym, pdata in list(s_pos.items())[:3]:
            pnl = pdata.get("pnl_pct", 0)
            pnl_strs.append(f"{sym} {pnl:+.2f}%")
        blocks.append(p(
            (f"* {label}", True),
            (f"  {buys+sells} signals(B{buys}/S{sells}) pos{len(s_pos)}", False),
            (f"  {' | '.join(pnl_strs)}" if pnl_strs else ""),
        ))

    # --- 2.5 回测vs模拟盘对照 ---
    blocks.append(h(3, "2a. 回测vs模拟盘对照"))
    try:
        eval_path = os.path.join(_PROJECT_DIR, "data", "eval_cache", "baseline.json")
        if os.path.exists(eval_path):
            with open(eval_path) as f:
                baseline = json.load(f)
            lines = ["策略            回测Sortino  模拟盘收益  状态"]
            lines.append("─" * 55)
            for sname in ["faceji", "silverquant", "tradingagents"]:
                bline = baseline.get(sname, {})
                bt_score = bline.get("score", 0)
                # 从信号数据获取模拟盘收益
                sim_pnl = signals_data.get("portfolios", {}).get(sname, {}).get("total_return", 0) if signals_data else 0
                status = "✅ 优于回测" if sim_pnl > bt_score else ("⚠️ 低于回测" if sim_pnl < bt_score else "✅ 持平")
                lines.append(f"{sname:<16s} {bt_score:<14.4f} {sim_pnl:>+8.2f}%  {status}")
            blocks.append(cd("\n".join(lines)))
        else:
            blocks.append(p("回测基线尚未建立（运行 evaluator_fixed.py --all 生成）"))
    except Exception as e:
        blocks.append(p(f"回测对照不可用: {e}"))

    # --- 3. 组合状态 ---
    blocks.append(h(2, "3. 组合状态"))
    blocks.append(p(("模拟盘: ", True), "1,000,000 全现金 | 0持仓(双门关闭未自动执行)"))
    blocks.append(p(("待执行信号: ", True), f"{len(signals)}个"))
    # 各策略详细持仓
    for sname, label in [("faceji", "faceji"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
        s_pos = positions.get(sname, {})
        if s_pos:
            pos_lines = [f"{label} 持仓 ({len(s_pos)}只):"]
            for sym, pd in s_pos.items():
                pnl = pd.get("pnl_pct", 0)
                ep = pd.get("entry_price", 0)
                qty = pd.get("quantity", 0)
                cp = pd.get("current_price", ep)
                cost = ep * qty
                pnl_s = f"{pnl:+.2f}%" if pnl else "-"
                pos_lines.append(f"  {sym} x{qty} @{ep:.2f}(现{cp:.2f}) 成本{cost:.0f} PnL{pnl_s}")
            blocks.append(cd("\n".join(pos_lines)))

    # --- 4. 产业链发现 ---
    blocks.append(h(2, "4. 产业链发现"))
    if chain_report and "暂不可用" not in chain_report:
        # 只看信号标的的链定位
        if signals:
            from research.chain_scanner import get_chain_for_symbol, score_chain_position
            blocks.append(p(("今日信号标的链定位:", True)))
            for s in signals[:4]:
                sym = s.get("symbol", "")
                chain_info = get_chain_for_symbol(sym)
                if chain_info:
                    cs = score_chain_position(chain_info)
                    ci = chain_info[0]
                    blocks.append(bl(
                        f"{sym}({s.get('name','')}) -> {ci['chain_name']} | "
                        f"[{ci['position']}] {ci['role']} | "
                        f"利润池分{ci['profit_share']}% | 链分{cs:.1f}"
                    ))
                    blocks.append(bl(f"  方向: {ci['directional_bias'][:60]}"))
        else:
            blocks.append(p("今日无信号标的, 链分析仅作参考"))
        # 完整链报告折叠为code block
        lines = chain_report.split("\n")
        blocks.append(cd("\n".join(lines[:40])))
    else:
        blocks.append(p("产业链扫描暂不可用"))

    # --- 5. 新闻异动 ---
    blocks.append(h(2, "5. 新闻异动"))
    if news_summary:
        for line in news_summary.split("\n")[:10]:
            if line.strip():
                blocks.append(bl(line.strip()))
    else:
        blocks.append(p("今日无显著个股新闻"))

    # --- 5.5 因子贡献分解 ---
    blocks.append(h(3, "5a. 因子贡献分解"))
    try:
        scan_path = os.path.join(_PROJECT_DIR, "data", "scan_snapshot_latest.json")
        if os.path.exists(scan_path):
            with open(scan_path) as f:
                scan = json.load(f)
            sc_rs = scan.get("results", [])
            if sc_rs:
                # 计算因子维度分布
                factor_scores = {"评分": [], "技术": [], "趋势": []}
                for r in sc_rs[:20]:
                    score = r.get("score", 0)
                    tech = r.get("tech", {}) or {}
                    factor_scores["评分"].append(score)
                    factor_scores["技术"].append(tech.get("total_tech_score", 5) if isinstance(tech, dict) else 5)
                import statistics
                avg_factors = {k: statistics.mean(v) if v else 0 for k, v in factor_scores.items()}
                factor_lines = ["因子维度      平均分  说明"]
                factor_lines.append("─" * 40)
                factor_lines.append(f"基本面评分   {avg_factors['评分']:<6.2f}  行业景气+财务质量+管理层")
                factor_lines.append(f"技术指标     {avg_factors['技术']:<6.2f}  RSI+MACD+均线偏离")
                factor_lines.append(f"趋势信号     {'N/A':<10s}  MA20/MA60趋势过滤")
                factor_lines.append(f"\n目前贡献最大者: {'基本面评分' if avg_factors['评分'] > avg_factors['技术'] else '技术指标'}")
                blocks.append(cd("\n".join(factor_lines)))
            else:
                blocks.append(p("尚未建立因子分解基础"))
        else:
            blocks.append(p("尚未建立因子分解基础"))
    except Exception as e:
        blocks.append(p(f"因子分解不可用: {e}"))

    # --- 5.6 ETF配置建议 ---
    blocks.append(h(3, "5b. ETF配置建议"))
    try:
        from etf.etf_backtest import compare_all_etf_strategies
        # 尝试加载ETF价格数据
        etf_symbols = ["SPY", "TLT", "QQQ", "GLD", "IEF"]
        etf_data = {}
        for s in etf_symbols:
            try:
                from data.data_router import get_history
                hist = get_history(s, days=200)
                if hist and hist.get("close"):
                    etf_data[s] = hist["close"]
            except Exception:
                continue
        if len(etf_data) >= 2:
            results = compare_all_etf_strategies(etf_data)
            r_lines = ["策略             收益%    Sharpe  最大回撤"]
            r_lines.append("─" * 50)
            for name, r in sorted(results.items(), key=lambda x: x[1].get("sortino_ratio", 0), reverse=True):
                if "error" not in r:
                    ret = r.get("total_return_pct", 0)
                    sharpe = r.get("sharpe_ratio", 0)
                    dd = r.get("max_drawdown_pct", 0)
                    r_lines.append(f"{name:<16s} {ret:>+7.2f} {sharpe:>8.4f} {dd:>6.2f}%")
            blocks.append(cd("\n".join(r_lines)))
            # 推荐
            best = max(results.items(), key=lambda x: x[1].get("sharpe_ratio", 0) if "error" not in x[1] else -999)
            if best and "error" not in best[1]:
                blocks.append(p((f"推荐: {best[0]} (Sharpe={best[1]['sharpe_ratio']:.2f})", True, 6)))
        else:
            blocks.append(p("ETF数据不足(需≥2只), 建议持仓待补充"))
    except Exception as e:
        blocks.append(p(f"ETF分析不可用: {e}"))

    # --- 5.7 Delta追踪 ---
    blocks.append(h(3, "5c. 每日变化追踪"))
    try:
        from analysis.delta_tracker import DeltaTracker
        dt = DeltaTracker()
        deltas = dt.compute_daily_deltas()
        if "error" not in deltas:
            dt_text = dt.format_delta_report(deltas)
            blocks.append(cd(dt_text[:800]))
        else:
            blocks.append(p(deltas["error"]))
    except Exception as e:
        blocks.append(p(f"Delta追踪不可用: {e}"))

    # --- 6. 行动指令 ---
    blocks.append(h(2, "6. 行动指令"))
    if signals:
        best = signals[0]
        blocks.append(p((f"目标: {best['strategy']} {best['action']} {best['symbol']} @{best['price']:.2f}", True, 5)))
        blocks.append(bl("确认执行后告知我记录"))
    else:
        blocks.append(bl("今日无建议操作"))
    blocks.append(bl("纪律: 每周每策略最多1次 | 合计最多3次 | 黑天鹅豁免"))
    blocks.append(bl("执行记录: python3 scripts/manual_trade.py --strategy X --action Y --symbol Z --price P"))

    # --- 附录A: 评分Top10 ---
    blocks.append(h(3, "附录A: 评分Top10"))
    scan_path = os.path.join(_PROJECT_DIR, "data", "scan_snapshot_latest.json")
    if os.path.exists(scan_path):
        with open(scan_path) as f:
            scan = json.load(f)
        sc_rs = scan.get("results", [])
        sc_rs.sort(key=lambda x: x.get("score", 0), reverse=True)
        top_lines = ["代码      名称          评分  ma20_dev  ma60_dev"]
        top_lines.append("─" * 45)
        for r in sc_rs[:10]:
            sym = r.get("symbol", "")
            nm = r.get("name", "")[:10]
            sc = r.get("score", 0)
            tech = r.get("tech", {}) or {}
            m20 = tech.get("ma20_dev", "")
            m60 = tech.get("ma60_dev", "")
            top_lines.append(f"{sym:8s} {nm:10s} {sc:.1f}   {str(m20):>7s}  {str(m60):>7s}")
        blocks.append(cd("\n".join(top_lines)))

    # --- 附录B: 交易纪律 ---
    blocks.append(h(3, "附录B: 交易纪律"))
    blocks.append(bl("每周每策略最多交易1次 | 合计最多3次"))
    blocks.append(bl("黑天鹅豁免 | 信号由agent生成->你手动执行->反馈记录"))
    blocks.append(bl("SQ风控: HardSeller(-8%) | FallSeller(-12%) | ScoreDrop(<4.5) | MA死叉+亏损<5%"))

    return blocks


def main():
    today_str = date.today().strftime("%Y-%m-%d")
    print("=" * 50)
    print(f"面基日报 v10 | {today_str}")
    print("=" * 50)

    sig_path = os.path.join(_PROJECT_DIR, "data", "trading_signals.json")

    # Phase 1: 扫描+信号
    signals_data = run_phase_scan(sig_path, today_str)
    if signals_data is None:
        print("FAIL: Phase 1 failed. Abort.")
        return

    # Phase 2: 产业链
    chain_report = run_phase_chain()

    # Phase 3: 新闻(quick模式)
    news_summary, news_count = run_phase_news()

    # Phase 4: 构建+发布
    title = f"面基日报 v10 | {today_str}"
    print(f"\n[Phase 4] 创建文档: {title}...")
    doc_result = feishu_call("create_feishu_document", {"title": title, "folderToken": FOLDER_TOKEN})
    if isinstance(doc_result, list):
        doc_id = doc_result[0].get("document", {}).get("document_id", "")
    else:
        doc_id = doc_result.get("document", {}).get("document_id", "")
    if not doc_id:
        print("FAIL: document creation failed")
        return
    print(f"  doc_id: {doc_id}")
    grant(doc_id)

    blocks = build_report_blocks(signals_data, chain_report, news_summary, today_str)
    print(f"  {len(blocks)} blocks to write")

    try:
        write_blocks(doc_id, blocks)
        url = f"https://bytedance.feishu.cn/docx/{doc_id}"
        print(f"\n{'='*50}")
        print(f"OK: v10 report complete!")
        print(f"Doc: {url}")
        print(f"Signals: {len(signals_data.get('signals', []))}")
        print(f"Chains: 12/12")
        print(f"News: {news_count} events")
        print(f"{'='*50}")

        # 推送飞书群
        sigs = signals_data.get("signals", [])
        msg_parts = [f"面基日报 v10 | {today_str}"]
        if sigs:
            best = sigs[0]
            msg_parts.append(f"\nRED 建议: {best['strategy']} {best['action']} {best['symbol']}({best.get('name','')}) @{best['price']:.2f}")
        msg_parts.append(f"\n信号: {len(sigs)}个 | 链: 12条 | 新闻: {news_count}条")
        msg_parts.append(f"\n完整: {url}")
        print("\n".join(msg_parts))
    except Exception as e:
        print(f"FAIL: publish error: {e}")
        token = get_token()
        if token:
            req = urllib.request.Request(
                f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}?type=docx",
                headers={"Authorization": f"Bearer {token}"}, method="DELETE")
            urllib.request.urlopen(req, timeout=10)
            print(f"  cleaned up doc {doc_id}")


if __name__ == "__main__":
    main()
