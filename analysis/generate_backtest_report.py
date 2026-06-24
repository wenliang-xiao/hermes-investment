"""
三方策略回测报告 → 飞书文档
"""
import sys, os, json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".."))

# 飞书文档构建
from feishu import build_report
from feishu.auth import get_tenant_token
from feishu.drive import create_document, add_member_to_doc
from feishu.block import make_block, make_table_block, make_divider_block

FOLDER_TOKEN = "QhIOfB63Sl6Kqmd81fycjR6jnDd"
USER_OPENID = "ou_e03d56632de9b44263adfc018f9d6e4d"


def load_results():
    path = os.path.join(ROOT, "data", "backtest_comparison.json")
    if not os.path.exists(path):
        print(f"❌ 结果文件不存在: {path}")
        return None
    with open(path) as f:
        return json.load(f)


def format_strategy_table(results):
    """格式化策略对比表格"""
    rows = [["指标", "面基 (当前)", "SilverQuant (组件化)", "TradingAgents (辩论制)"]]
    metrics = [
        ("收益率 %", "total_return_pct"),
        ("总盈亏 ¥", "total_return_cny"),
        ("最终价值 ¥", "value"),
        ("现金 ¥", "cash"),
        ("持仓数", "positions_count"),
        ("开仓次数", "total_trades_opened"),
        ("平仓次数", "total_trades_closed"),
        ("胜率 %", "win_rate"),
        ("最大回撤 %", "max_drawdown_pct"),
        ("Sharpe 比", "sharpe_ratio"),
    ]
    for label, key in metrics:
        row = [label]
        for sname in ["faceji", "silverquant", "tradingagents"]:
            val = results.get(sname, {}).get(key, "-")
            if isinstance(val, float):
                row.append(f"{val:,.2f}" if abs(val) >= 1 else f"{val}")
            elif isinstance(val, int):
                row.append(f"{val:,}")
            else:
                row.append(str(val))
        rows.append(row)
    return rows


def format_trade_table(trades, name):
    """格式化交易明细表"""
    if not trades:
        return [["无交易记录"]]

    rows = [["日期", "标的", "操作", "价格", "数量", "盈亏¥", "原因"]]
    for t in trades:
        rows.append([
            t.get("date", ""),
            t.get("symbol", ""),
            t.get("action", ""),
            f'{t.get("price", 0):.2f}',
            str(t.get("quantity", 0)),
            f'{t.get("pnl", 0):+.2f}' if t.get("pnl") else "-",
            t.get("reason", "")
        ])
    return rows


def build_daily_equity_section(results):
    """构建净值曲线数据"""
    sections = []
    for sname, label in [("faceji", "面基"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
        data = results.get(sname, {}).get("daily_values", [])
        if data:
            vals = [d["value"] for d in data]
            dates = [d["date"] for d in data]
            sections.append({
                "name": label,
                "equity": data,
                "max_dd": results[sname]["max_drawdown_pct"],
                "sharpe": results[sname]["sharpe_ratio"],
                "return_pct": results[sname]["total_return_pct"],
            })
    return sections


def generate_report():
    data = load_results()
    if not data:
        return

    results = data["results"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.now().strftime("%Y-%m-%d")

    # ─── 创建文档 ───
    title = f"📊 三方策略回测报告 · {today}"
    doc_id = create_document(title, folder_token=FOLDER_TOKEN)
    print(f"📄 文档创建: {doc_id}")

    # 添加协作者
    add_member_to_doc(doc_id, USER_OPENID, "full_access")

    # ─── 构建文档块 ───
    blocks = []

    # 封面摘要
    blocks.append(make_block("heading1", text="📊 三方策略回测报告"))
    blocks.append(make_block("text", text=f"执行时间: {data.get('run_date', now)}"))
    blocks.append(make_block("text", text=f"回测窗口: {data.get('date_range', 'N/A')} ({data.get('days_analyzed', 0)}个交易日)"))
    blocks.append(make_block("text", text=f"评分标的: {data.get('scored_stocks', 0)}只"))
    blocks.append(make_divider_block())

    # ── 策略核心对比 ──
    blocks.append(make_block("heading2", text="📈 策略核心对比"))
    table_data = format_strategy_table(results)
    blocks.append(make_table_block(table_data))
    blocks.append(make_divider_block())

    # ── 策略详细分析 ──
    for sname, label, color in [
        ("faceji", "① 面基 (当前系统)", "blue"),
        ("silverquant", "② SilverQuant 组件化", "green"),
        ("tradingagents", "③ TradingAgents 辩论制", "purple"),
    ]:
        s = results.get(sname, {})
        if not s:
            continue

        blocks.append(make_block("heading2", text=label))

        # 核心指标
        blocks.append(make_block("heading3", text="核心表现"))
        metrics_text = (
            f"📊 最终价值: ¥{s.get('value', 0):,.2f} | "
            f"收益率: {s.get('total_return_pct', 0):+.2f}% | "
            f"总盈亏: ¥{s.get('total_return_cny', 0):+,.2f}\n"
            f"📈 Sharpe: {s.get('sharpe_ratio', 0):.2f} | "
            f"最大回撤: {s.get('max_drawdown_pct', 0):.2f}% | "
            f"胜率: {s.get('win_rate', 0):.1f}%\n"
            f"🔄 开/平仓: {s.get('total_trades_opened', 0)}次 / {s.get('total_trades_closed', 0)}次 | "
            f"持仓: {s.get('positions_count', 0)}只"
        )
        blocks.append(make_block("text", text=metrics_text))
        blocks.append(make_block("text", text=""))

        # 交易明细
        trades = s.get("trades", [])
        if trades:
            blocks.append(make_block("heading3", text="逐笔交易明细"))
            trade_table = format_trade_table(trades, sname)
            blocks.append(make_table_block(trade_table))

        blocks.append(make_divider_block())

    # ── 净值曲线（文本版） ──
    blocks.append(make_block("heading2", text="📉 净值曲线数据"))
    blocks.append(make_block("text", text="(前三日 + 后三日 采样展示)"))
    for sname, label in [("faceji", "面基"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
        daily_vals = results.get(sname, {}).get("daily_values", [])
        if daily_vals:
            # Sample: first 3, last 3
            samples = daily_vals[:3] + [{"date": "...", "value": "..."}] + daily_vals[-3:]
            sample_text = " | ".join([f"{d['date']}: ¥{d['value']:,.2f}" for d in daily_vals[:5]])
            blocks.append(make_block("text", text=f"**{label}**: {sample_text}"))
            # Summary
            start_val = daily_vals[0]["value"]
            end_val = daily_vals[-1]["value"]
            blocks.append(make_block("text", text=f"  📍 {daily_vals[0]['date']}: ¥{start_val:,.2f} → {daily_vals[-1]['date']}: ¥{end_val:,.2f} ({((end_val-start_val)/start_val*100):+.2f}%)"))

    blocks.append(make_divider_block())

    # ── 结论 ──
    blocks.append(make_block("heading2", text="🎯 结论与建议"))

    # Find best strategy
    best_name = ""
    best_return = -999
    for sname, label in [("faceji", "面基"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
        r = results.get(sname, {}).get("total_return_pct", -999)
        if r > best_return:
            best_return = r
            best_name = label

    blocks.append(make_block("text", text=f"🏆 最优策略: **{best_name}** ({best_return:+.2f}%)"))

    # Strategy comparison insights
    faceji = results.get("faceji", {})
    sq = results.get("silverquant", {})
    ta = results.get("tradingagents", {})

    insights = []
    if faceji.get("sharpe_ratio", 0) > max(sq.get("sharpe_ratio",0), ta.get("sharpe_ratio",0)):
        insights.append("✅ 面基策略Sharpe比最高——风险调整后收益最优")
    if sq.get("max_drawdown_pct", 999) < min(faceji.get("max_drawdown_pct", 999), ta.get("max_drawdown_pct", 999)):
        insights.append("✅ SilverQuant组件化卖点有效控制了最大回撤")
    if ta.get("win_rate", 0) > max(faceji.get("win_rate",0), sq.get("win_rate",0)):
        insights.append("✅ TradingAgents辩论制胜率更高——但交易次数少，样本有限")

    for ins in insights:
        blocks.append(make_block("text", text=ins))

    blocks.append(make_block("text", text=""))
    blocks.append(make_block("text", text="⚠️ 注意事项:"))
    notes = [
        "评分基于当前扫描结果（静态），未模拟每日因子变化",
        "实际盘中滑点/冲击成本未纳入模型",
        "买卖价格为当日收盘价（非盘中实时）",
        "回测窗口较短（60个交易日），统计显著性有限",
    ]
    for n in notes:
        blocks.append(make_block("text", text=f"  • {n}"))

    # ─── 写入文档 ───
    build_report(doc_id, blocks)
    print(f"\n✅ 报告已生成: https://bytedance.feishu.cn/docx/{doc_id}")
    return doc_id


if __name__ == "__main__":
    doc_id = generate_report()
    if doc_id:
        print(f"\n📎 报告链接: https://bytedance.feishu.cn/docx/{doc_id}")
