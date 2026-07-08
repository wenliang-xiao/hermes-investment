"""
analysis/deep_research_v2.py — LLM驱动的深度研报生成器 v2

用法:
    from research.deep_research_v2 import DeepResearchGenerator

    gen = DeepResearchGenerator()
    report = gen.generate_report("300502")       # 单只标的
    gen.save_report("300502", report)            # 保存到 data/research_reports/

    或批量:
    gen.run_batch(max_stocks=5)                  # 从 deep pool 读取并生成

差异vs v1:
    v1 使用纯规则引擎生成 8 维研报
    v2 使用 GLM-4-Flash LLM 分析多源数据，生成结构化深度报告
"""

from __future__ import annotations

import json, math, os, sys, urllib.request, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class DeepResearchGenerator:
    """LLM 驱动深度研报生成器 — 聚合多源数据 + GLM-4-Flash 分析"""

    def __init__(self):
        self._watchlist = None
        self._chains = None

    # ═══════════════════════════════════════════
    # 数据加载
    # ═══════════════════════════════════════════

    @property
    def watchlist(self) -> dict:
        if self._watchlist is None:
            try:
                from domain import WATCHLIST
                self._watchlist = WATCHLIST
            except Exception:
                try:
                    from config import WATCHLIST
                    self._watchlist = WATCHLIST
                except Exception:
                    self._watchlist = {}
        return self._watchlist

    @property
    def chains(self) -> dict:
        if self._chains is None:
            try:
                from dashboard.shared import _CHAIN_NAMES
                self._chains = _CHAIN_NAMES
            except Exception:
                self._chains = {}
        return self._chains

    def _load_deep_pool(self) -> list[dict]:
        path = ROOT / "data" / "pool" / "deep.json"
        if not path.exists():
            return []
        with open(path) as f:
            raw = f.read().strip()
            return json.loads(raw) if raw else []

    def _get_watchlist_info(self, symbol: str) -> dict:
        """从 WATCHLIST 获取标的元信息"""
        info = self.watchlist.get(symbol, {})
        if isinstance(info, dict):
            return info
        return {"name": str(info)}

    def _get_chain(self, symbol: str) -> str:
        """获取产业链归属"""
        c = self.chains.get(symbol, "")
        if not c:
            info = self._get_watchlist_info(symbol)
            c = info.get("chain", "")
        return c or "其他"

    def _get_history(self, symbol: str, days: int = 120) -> Optional[dict]:
        """获取历史日线"""
        try:
            from data.data_router import get_history
            return get_history(symbol, days=days)
        except Exception as e:
            logger.warning(f"获取历史日线失败 {symbol}: {e}")
            return None

    def _get_rt(self, symbol: str) -> Optional[dict]:
        """获取实时行情"""
        try:
            from data.data_router import get_rt
            return get_rt(symbol)
        except Exception as e:
            logger.warning(f"获取实时行情失败 {symbol}: {e}")
            return None

    def _get_news(self, symbol: str, name: str = "") -> list[dict]:
        """从新闻缓存中查找该标的的相关新闻"""
        cache_path = ROOT / "data" / "news_cache.json"
        if not cache_path.exists():
            return []

        try:
            with open(cache_path) as f:
                cache = json.load(f)
        except Exception:
            return []

        related = []
        search_terms = [symbol]
        if name:
            search_terms.append(name)
        # 截短名称（如"新易盛"→"新易"）
        if len(name) >= 2:
            search_terms.append(name[:2])

        for cat_key, items in cache.get("categories", {}).items():
            for item in items:
                title = item.get("title", "")
                content = item.get("content", "")
                text = title + content
                if any(term in text for term in search_terms):
                    related.append({
                        "title": title[:150],
                        "content": content[:200],
                        "published": item.get("published", ""),
                        "sentiment": item.get("sentiment", "neutral"),
                        "source": item.get("source", ""),
                    })
                    if len(related) >= 10:
                        break
            if len(related) >= 10:
                break

        return related

    # ═══════════════════════════════════════════
    # 数据聚合
    # ═══════════════════════════════════════════

    def gather_stock_data(self, symbol: str) -> dict:
        """采集标的所有可用数据"""
        wl_info = self._get_watchlist_info(symbol)
        name = wl_info.get("name", symbol)
        chain = self._get_chain(symbol)
        focus = wl_info.get("focus", "")
        tier = wl_info.get("tier", "")

        # 从 pool 获取因子评分
        factor_scores = {}
        overall_score = 0.0
        factor_breakdown = {}
        date_added = ""
        stoplist_passed = None

        for item in self._load_deep_pool():
            if item.get("symbol") == symbol:
                factor_scores = item.get("scores", {})
                overall_score = item.get("score", 0.0)
                factor_breakdown = item.get("factor_breakdown", {})
                date_added = item.get("date_added", "")
                stoplist_passed = item.get("stoplist_passed")
                break

        # 价格/技术数据
        hist = self._get_history(symbol, days=120)
        rt = self._get_rt(symbol)

        price_data = self._compute_price_metrics(hist, rt)

        # 新闻
        news = self._get_news(symbol, name)

        return {
            "symbol": symbol,
            "name": name,
            "chain": chain,
            "focus": focus,
            "tier": tier,
            "overall_score": overall_score,
            "factor_scores": factor_scores,
            "factor_breakdown": factor_breakdown,
            "date_added": date_added,
            "stoplist_passed": stoplist_passed,
            "price_data": price_data,
            "news": news,
        }

    def _compute_price_metrics(self, hist: Optional[dict], rt: Optional[dict]) -> dict:
        """计算价格和技术指标"""
        result = {}
        closes = []
        dates = []

        if hist:
            closes = [c for c in (hist.get("close") or []) if c and c > 0]
            dates = hist.get("dates") or []

        current_price = (rt.get("price") if rt else (closes[-1] if closes else 0)) or 0
        pe = rt.get("pe") if rt else None
        name_rt = rt.get("name", "") if rt else ""

        result.update({
            "current_price": round(current_price, 2) if current_price else 0,
            "pe": round(pe, 2) if pe else None,
            "name": name_rt,
        })

        if closes:
            import numpy as np
            result["data_days"] = len(closes)

            # MA
            for period, key in [(5, "ma5"), (20, "ma20"), (60, "ma60")]:
                if len(closes) >= period:
                    result[key] = round(float(np.mean(closes[-period:])), 2)

            # 趋势判断
            if result.get("ma20") and result.get("ma60") and current_price:
                if current_price > result["ma20"] > result["ma60"]:
                    result["trend"] = "上升趋势(多头排列)"
                elif current_price < result["ma20"] < result["ma60"]:
                    result["trend"] = "下降趋势(空头排列)"
                else:
                    result["trend"] = "震荡"

            # RSI (14)
            if len(closes) > 14:
                gains = [max(0, closes[i] - closes[i - 1]) for i in range(-14, 0)]
                losses = [max(0, closes[i - 1] - closes[i]) for i in range(-14, 0)]
                avg_gain = float(np.mean(gains))
                avg_loss = float(np.mean(losses))
                if avg_loss == 0:
                    result["rsi_14"] = 100.0
                else:
                    rs = avg_gain / avg_loss
                    result["rsi_14"] = round(100 - 100 / (1 + rs), 1)

            # MACD 信号 (EMA12/EMA26)
            if len(closes) >= 26:
                ema12 = self._calc_ema(closes, 12)
                ema26 = self._calc_ema(closes, 26)
                dif = ema12 - ema26
                # Signal line = EMA9 of DIF
                difs = []
                for i in range(26, len(closes)):
                    ema12_i = self._calc_ema(closes[:i + 1], 12)
                    ema26_i = self._calc_ema(closes[:i + 1], 26)
                    difs.append(ema12_i - ema26_i)
                if len(difs) >= 9:
                    dea = self._calc_ema(diffs, 9)
                    result["macd_dif"] = round(dif, 4)
                    result["macd_dea"] = round(dea, 4)
                    result["macd_signal"] = "金叉(看涨)" if dif > dea else "死叉(看跌)"

            # 区间回报
            for period in [5, 20, 60]:
                if len(closes) > period:
                    ret = (closes[-1] / closes[-1 - period] - 1) * 100
                    result[f"ret_{period}d"] = round(ret, 2)

            # 年化波动率(20d)
            if len(closes) > 20:
                daily_rets = [closes[i] / closes[i - 1] - 1 for i in range(-19, 0)]
                vol = float(np.std(daily_rets)) * math.sqrt(252) * 100
                result["vol_20d_annual"] = round(vol, 1)

            # 高点/低点
            if len(closes) >= 120:
                result["high_120d"] = round(float(max(closes[-120:])), 2)
                result["low_120d"] = round(float(min(closes[-120:])), 2)
                if result["high_120d"] > 0:
                    pct_from_high = (current_price / result["high_120d"] - 1) * 100
                    result["pct_from_120d_high"] = round(pct_from_high, 1)

        return result

    @staticmethod
    def _calc_ema(data: list[float], period: int) -> float:
        if len(data) < period:
            return float(sum(data) / len(data))
        import numpy as np
        alpha = 2.0 / (period + 1)
        ema = float(np.mean(data[:period]))
        for val in data[period:]:
            ema = alpha * val + (1 - alpha) * ema
        return ema

    # ═══════════════════════════════════════════
    # Prompt 构建
    # ═══════════════════════════════════════════

    def build_report_prompt(self, symbol: str, stock_data: dict) -> str:
        """构建 LLM 分析 prompt"""
        parts = []

        parts.append(f"请对以下A股标的进行深度分析，生成结构化研报。\n")
        parts.append(f"标的: {symbol} {stock_data['name']}")
        parts.append(f"产业链: {stock_data['chain']}")
        parts.append(f"核心关注: {stock_data.get('focus', '')}")

        # 因子评分
        fs = stock_data.get("factor_scores", {})
        if fs:
            factor_names = {
                "quality": "质量", "value": "价值", "growth": "成长",
                "momentum": "动量", "low_vol": "低波", "sentiment": "情绪/资金",
                "dividend": "股息", "risk": "风险"
            }
            parts.append(f"\n## 因子评分 (综合: {stock_data['overall_score']:.4f})")
            for k, v in sorted(fs.items(), key=lambda x: -x[1]):
                label = factor_names.get(k, k)
                parts.append(f"- {label}({k}): {v:.4f}")

        # 价格/技术数据
        pd_data = stock_data.get("price_data", {})
        if pd_data:
            parts.append(f"\n## 价格与技术指标")
            if pd_data.get("current_price"):
                parts.append(f"- 现价: ¥{pd_data['current_price']}")
            if pd_data.get("pe"):
                parts.append(f"- PE: {pd_data['pe']}")
            if pd_data.get("ma5"):
                parts.append(f"- MA5: {pd_data['ma5']}  MA20: {pd_data.get('ma20', '')}  MA60: {pd_data.get('ma60', '')}")
            if pd_data.get("trend"):
                parts.append(f"- 趋势: {pd_data['trend']}")
            if pd_data.get("rsi_14"):
                parts.append(f"- RSI(14): {pd_data['rsi_14']}")
            if pd_data.get("macd_signal"):
                parts.append(f"- MACD: DIF={pd_data.get('macd_dif', '')} DEA={pd_data.get('macd_dea', '')} → {pd_data['macd_signal']}")
            for period in [5, 20, 60]:
                key = f"ret_{period}d"
                if key in pd_data:
                    parts.append(f"- {period}日回报: {pd_data[key]:+.2f}%")
            if pd_data.get("vol_20d_annual"):
                parts.append(f"- 20日年化波动率: {pd_data['vol_20d_annual']}%")
            if pd_data.get("pct_from_120d_high") is not None:
                parts.append(f"- 距120日高点: {pd_data['pct_from_120d_high']}%")

        # 新闻情绪
        news_list = stock_data.get("news", [])
        if news_list:
            parts.append(f"\n## 近期新闻 (共{len(news_list)}条)")
            for n in news_list[:5]:
                sent = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(n.get("sentiment", ""), "")
                parts.append(f"- [{sent}] {n.get('published', '')[:10]} {n.get('title', '')}")
        else:
            parts.append(f"\n## 近期新闻: 暂无匹配新闻")

        # 要求
        parts.append(f"""
---
请按以下结构输出分析报告（JSON格式，直接输出JSON不要额外说明）：

```json
{{
  "symbol": "{symbol}",
  "name": "{stock_data['name']}",
  "sections": {{
    "公司概况": "主营业务、产业链位置、竞争优势分析...",
    "财务健康度": "ROE/毛利率/负债率/现金流分析...",
    "估值分析": "PE/PB历史分位评估，同行对比...",
    "技术面信号": "MA排列/RSI/MACD趋势判断...",
    "资金面": "成交量/资金流向信号...",
    "新闻情绪": "近期新闻汇总及情感倾向分析...",
    "风险提示": "主要风险因素及应对策略...",
    "操作建议": "买入区间/止损位/仓位建议/关键催化剂..."
  }},
  "score": {stock_data['overall_score']},
  "signal": "STRONGBUY/BUY/HOLD/SELL (根据综合判断)"
}}
```

注意事项:
1. 每个section用中文输出，200-400字，简洁专业
2. 基于提供的数据进行分析，对于数据不足的维度可以保守判断
3. signal判断: >=0.63 → STRONGBUY, >=0.48 → BUY, >=0.35 → HOLD, 否则SELL
4. 操作建议要给出具体的买入区间和止损价位
""")
        return "\n".join(parts)

    # ═══════════════════════════════════════════
    # GLM API 调用
    # ═══════════════════════════════════════════

    def _call_glm(self, system_prompt: str, user_prompt: str, max_tokens: int = 3000) -> str:
        """调用 GLM-4-Flash API (与 scripts/news_pipeline.py 相同模式)"""
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("ARK_API_KEY", "")
            if not api_key:
                return f'{{"error": "ARK_API_KEY not configured"}}'

            url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
            data = {
                "model": "glm-4-flash",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=60)
            result = json.loads(resp.read())
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return content
        except Exception as e:
            logger.error(f"GLM API 调用失败: {e}")
            return f'{{"error": "GLM API 调用失败: {e}"}}'

    # ═══════════════════════════════════════════
    # 报告生成 & 保存
    # ═══════════════════════════════════════════

    def generate_report(self, symbol: str) -> dict:
        """对单个标的生成 LLM 研报（完整流程）"""
        logger.info(f"开始生成研报: {symbol}")

        # 1. 采集数据
        stock_data = self.gather_stock_data(symbol)
        name = stock_data.get("name", symbol)

        # 2. 构建 prompt
        system_prompt = (
            "你是一个专业的A股投资分析师，擅长从多维度分析个股。"
            "输出简洁、专业、有数据支撑。"
            "请严格按照要求的JSON格式输出，不要添加额外说明。"
            "每个section控制在200-400字。"
        )
        user_prompt = self.build_report_prompt(symbol, stock_data)

        # 3. 调用 LLM
        logger.info(f"  调用 GLM-4-Flash 分析 {symbol} ({name})...")
        raw_response = self._call_glm(system_prompt, user_prompt)

        # 4. 解析 JSON
        try:
            # 尝试提取 JSON (可能包含 ```json ... ``` 包裹)
            if "```json" in raw_response:
                json_start = raw_response.index("```json") + 7
                json_end = raw_response.index("```", json_start)
                json_str = raw_response[json_start:json_end].strip()
            elif "```" in raw_response:
                json_start = raw_response.index("```") + 3
                json_end = raw_response.index("```", json_start)
                json_str = raw_response[json_start:json_end].strip()
            else:
                json_str = raw_response.strip()
            report = json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"  LLM 返回解析失败，使用回退: {e}")
            # 回退：用原始文本构建报告
            report = {
                "symbol": symbol,
                "name": name,
                "sections": {
                    "公司概况": stock_data.get("focus", "数据暂缺"),
                    "财务健康度": f"综合评分 {stock_data.get('overall_score', 0):.4f}",
                    "估值分析": f"PE={stock_data.get('price_data', {}).get('pe', 'N/A')}",
                    "技术面信号": stock_data.get("price_data", {}).get("trend", "N/A"),
                    "资金面": "待补充",
                    "新闻情绪": f"匹配到 {len(stock_data.get('news', []))} 条新闻",
                    "风险提示": "流动性/政策/行业竞争",
                    "操作建议": "建议观望，等待进一步信号",
                },
                "raw_llm_response": raw_response[:500],
            }

        # 5. 附加元信息
        report["symbol"] = symbol
        report["name"] = name
        report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        report.setdefault("score", stock_data.get("overall_score", 0.0))
        report.setdefault("signal", "HOLD")
        report["chain"] = stock_data.get("chain", "")
        report["data_summary"] = {
            "score": stock_data["overall_score"],
            "factor_count": len(stock_data.get("factor_scores", {})),
            "price_days": stock_data.get("price_data", {}).get("data_days", 0),
            "news_count": len(stock_data.get("news", [])),
        }

        logger.info(f"  ✅ {symbol} 研报生成完成, signal={report.get('signal')}, score={report.get('score')}")
        return report

    def save_report(self, symbol: str, report: dict) -> str:
        """保存研报到 data/research_reports/"""
        output_dir = ROOT / "data" / "research_reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_symbol = symbol.replace(".", "_").replace(":", "_").replace("=", "_")
        filename = f"{safe_symbol}_{datetime.now().strftime('%Y%m%d')}.json"
        filepath = output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"  研报已保存: {filepath}")
        return str(filepath)

    # ═══════════════════════════════════════════
    # 批量运行
    # ═══════════════════════════════════════════

    def _get_existing_report_date(self, symbol: str) -> Optional[str]:
        """检查该标的最近研报日期，返回 None 表示无报告或过期"""
        report_dir = ROOT / "data" / "research_reports"
        if not report_dir.exists():
            return None

        safe_symbol = symbol.replace(".", "_").replace(":", "_").replace("=", "_")
        prefix = f"{safe_symbol}_"
        dates = []
        for f in report_dir.glob(f"{prefix}*.json"):
            date_part = f.stem.replace(prefix, "")
            if len(date_part) == 8 and date_part.isdigit():
                dates.append(date_part)

        if dates:
            return max(dates)
        return None

    def run_batch(self, max_stocks: int = 5, force: bool = False) -> dict:
        """从 deep pool 读取标的并生成研报

        Args:
            max_stocks: 每批次最多处理的标的数量
            force: 是否强制重新生成（忽略已有<7天的报告）

        Returns:
            {"success": 3, "skipped": 1, "failed": 1, "details": [...]}
        """
        deep_pool = self._load_deep_pool()
        if not deep_pool:
            logger.info("deep pool 为空，跳过")
            return {"success": 0, "skipped": 0, "failed": 0, "details": []}

        # 过滤：跳过已有<7天报告的标的
        candidates = []
        cutoff_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

        for item in deep_pool:
            symbol = item.get("symbol", "")
            if not symbol:
                continue

            last_date = self._get_existing_report_date(symbol)
            if not force and last_date and last_date >= cutoff_date:
                logger.info(f"  {symbol}: 已有最新研报 ({last_date})，跳过")
                continue
            candidates.append(item)

        # 限制数量
        candidates = candidates[:max_stocks]

        if not candidates:
            logger.info("所有标的均有最新研报，无需重新生成")
            return {"success": 0, "skipped": len(deep_pool), "failed": 0, "details": []}

        logger.info(f"将从 deep pool ({len(deep_pool)}只) 中处理 {len(candidates)} 只标的")

        results = {"success": 0, "skipped": len(deep_pool) - len(candidates), "failed": 0, "details": []}

        for i, item in enumerate(candidates):
            symbol = item.get("symbol", "")
            name = item.get("name", self._get_watchlist_info(symbol).get("name", symbol))
            logger.info(f"[{i + 1}/{len(candidates)}] {symbol} ({name})")

            try:
                report = self.generate_report(symbol)
                filepath = self.save_report(symbol, report)
                results["success"] += 1
                results["details"].append({
                    "symbol": symbol,
                    "status": "success",
                    "file": filepath,
                    "signal": report.get("signal", ""),
                    "score": report.get("score", 0),
                })
            except Exception as e:
                logger.error(f"  ❌ {symbol} 失败: {e}")
                import traceback
                traceback.print_exc()
                results["failed"] += 1
                results["details"].append({
                    "symbol": symbol,
                    "status": "error",
                    "error": str(e),
                })

        # 汇总
        logger.info(f"批量生成完成: 成功 {results['success']}, 跳过 {results['skipped']}, 失败 {results['failed']}")
        return results


def get_latest_report(symbol: str) -> Optional[dict]:
    """获取某标的最新研报（供 Dashboard API 使用）"""
    report_dir = Path(__file__).resolve().parent.parent / "data" / "research_reports"
    if not report_dir.exists():
        return None

    safe_symbol = symbol.replace(".", "_").replace(":", "_").replace("=", "_")
    prefix = f"{safe_symbol}_"
    matches = sorted(report_dir.glob(f"{prefix}*.json"), reverse=True)
    if not matches:
        return None

    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


def list_all_reports() -> list[dict]:
    """列出所有研报索引"""
    report_dir = Path(__file__).resolve().parent.parent / "data" / "research_reports"
    if not report_dir.exists():
        return []

    results = []
    for f in sorted(report_dir.glob("*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            results.append({
                "symbol": data.get("symbol", ""),
                "name": data.get("name", ""),
                "generated_at": data.get("generated_at", ""),
                "signal": data.get("signal", ""),
                "score": data.get("score", 0),
                "file": f.name,
            })
        except Exception:
            pass
    return results


if __name__ == "__main__":
    # 快速测试
    gen = DeepResearchGenerator()
    report = gen.generate_report("300502")
    print(json.dumps(report, ensure_ascii=False, indent=2))
