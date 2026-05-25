"""
宏观/趋势引擎 v3.1 — 三源融合
面基货币-信用四象限 + LDS CPI驱动策略开关 + Vibe趋势温度

分层输出:
  1. 宏观气候 → 货币信用四象限
  2. 经济状态 → CPI/PMI综合判断
  3. 趋势温度 → 凉平温热（基于国运线偏离）
  4. 策略开关 → on / limited / off
  5. 因子权重 → 动态配比
  6. 建议仓位 → 综合以上全部
"""
import json, os, logging
from datetime import datetime, timedelta
import numpy as np
from . import config
from .data_layer import get_macro_data, get_index_data

logger = logging.getLogger(__name__)


class MacroEngine:
    def __init__(self):
        self.macro_data = {}
        self.macro_data_ok = False
        self.macro_warnings = []
        self.quadrant = "数据未加载"
        self.regime = "default"
        self.trend_temp = "平"
        self.strategy_switch = "hold"
        self.suggested_position = 0.3
        self.factor_weights = config.FACTOR_WEIGHTS["default"]
        self.last_refreshed = None

    def refresh(self, force=False):
        cache_file = os.path.join(os.path.dirname(__file__), "data", "macro_engine_cache.json")

        if not force and self.last_refreshed:
            age = (datetime.now() - self.last_refreshed).total_seconds()
            if age < 3600:
                return self.summarize()

        self.macro_warnings = []

        try:
            raw = get_macro_data()
            cpi = raw.get("cpi")
            pmi = raw.get("pmi")
            if cpi is None or pmi is None:
                raise ValueError(f"宏观数据不完整: cpi={cpi}, pmi={pmi}")
            self.macro_data = raw
            self.macro_data_ok = True
        except Exception as e:
            self.macro_data_ok = False
            self.macro_warnings.append(f"⚠️ 宏观数据获取失败({e})，策略开关暂停，维持现有仓位")
            self.quadrant = "数据不可用"
            self.regime = "default"
            self.strategy_switch = "hold"
            self.suggested_position = 0.3
            self.last_refreshed = datetime.now()
            return self.summarize()

        self._classify_quadrant()
        self._calc_trend_temp()
        self._calc_factor_weights()
        self._calc_strategy_switch()
        self._calc_dual_gate()
        self._calc_position()
        self.last_refreshed = datetime.now()

        # 写缓存
        try:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, "w") as f:
                json.dump(self.summarize(), f, ensure_ascii=False)
        except:
            pass

        return self.summarize()

    # ═══ ① 货币-信用四象限（面基框架核心） ═══
    def _classify_quadrant(self):
        md = self.macro_data
        shibor = md.get("shibor", 1.75) or 1.75
        m2g = md.get("m2_growth", 7.2) or 7.2

        t = config.MACRO_THRESHOLDS
        loose_money = "宽货币" if shibor < t["shibor_loose"] else "紧货币"
        loose_credit = "宽信用" if m2g > t["m2_loose"] else "紧信用"
        self.quadrant = f"{loose_money}·{loose_credit}"

        # 四象限→经济状态映射
        quadrant_map = {
            "宽货币·宽信用": ("经济扩张", "扩张期"),
            "宽货币·紧信用": ("衰退复苏", "复苏期"),
            "紧货币·宽信用": ("经济过热", "过热期"),
            "紧货币·紧信用": ("经济衰退", "衰退期"),
        }
        self.regime_desc, self.regime = quadrant_map.get(self.quadrant, ("数据不足", "复苏期"))

    # ═══ ② 趋势温度 + 国运线（LDS核心框架） ═══
    def _calc_trend_temp(self):
        self.guoyun_price = None  # 20年均线 / 240月均线
        self.price_deviation = None  # 当前偏离度%
        self.guoyun_note = ""
        
        try:
            idx = get_index_data("sh000001", 120)
            if idx.empty or len(idx) < 20:
                self.trend_temp = "平"
                return

            idx["ma60"] = idx["close"].rolling(60).mean()
            price = idx.iloc[-1]["close"]
            ma60 = idx.iloc[-1]["ma60"]
            if np.isnan(ma60) or ma60 == 0:
                self.trend_temp = "平"
                return

            deviation = (price - ma60) / ma60
            if deviation > 0.15: self.trend_temp = "热"
            elif deviation > 0.05: self.trend_temp = "温"
            elif deviation > -0.05: self.trend_temp = "平"
            else: self.trend_temp = "凉"
            
            # 国运线 — 上证240月均线（约20年）
            try:
                idx_long = get_index_data("sh000001", 5500)
                if idx_long is not None and len(idx_long) >= 240:
                    idx_long["ma240"] = idx_long["close"].rolling(240).mean()
                    p240 = idx_long.iloc[-1]["ma240"]
                    if p240 is not None and not np.isnan(float(p240)):
                        self.guoyun_price = round(float(p240), 0)
                        self.price_deviation = round(
                            (float(price) - self.guoyun_price) / self.guoyun_price * 100, 1
                        )
                        if self.price_deviation > 20:
                            zone = "⚠️ 大幅高于国运线"
                        elif self.price_deviation > 10:
                            zone = "偏高区域"
                        elif self.price_deviation > 0:
                            zone = "略高于国运线"
                        elif self.price_deviation > -10:
                            zone = "接近国运线，底部区域"
                        else:
                            zone = "🔴 大幅低于国运线"
                        self.guoyun_note = f"{zone}，偏离{self.price_deviation:+.1f}%"
                    else:
                        logger.warning("[国运线] ma240计算结果为NaN，历史数据可能不足240条")
                else:
                    logger.warning("[国运线] 历史数据不足，获取到%d条，需要>=240条",
                                   len(idx_long) if idx_long is not None else 0)
            except Exception as e:
                logger.warning("[国运线] 计算失败: %s", e)

        except Exception as e:
            logger.warning("[趋势温度] 计算失败: %s，设为默认值'平'", e)
            self.trend_temp = "平"
    
    # ═══ ②.5 板块温度统计（LDS趋势周期：凉→平→温→热） ═══
    def _calc_sector_temp(self, scan_results=None):
        """统计各板块温度，输出LDS双门判断所需"""
        self.sector_temp_counts = {"热": 0, "温": 0, "平": 0, "凉": 0}
        self.sector_temp_detail = {}
        
        if not scan_results:
            return
            
        from .config import MACRO_SECTOR_ROTATION
        # 按板块聚合
        sector_by_regime = MACRO_SECTOR_ROTATION.get(self.regime, MACRO_SECTOR_ROTATION.get("default", {}))
        favored = sector_by_regime.get("favored", [])
        
        # 简单按涨跌分温凉
        for r in scan_results:
            chg = r.get("change_pct", 0) or 0
            sector = r.get("sector", "其他")
            if sector not in self.sector_temp_detail:
                self.sector_temp_detail[sector] = {"count": 0, "avg_chg": 0, "stocks": []}
            self.sector_temp_detail[sector]["count"] += 1
            self.sector_temp_detail[sector]["avg_chg"] += chg
            self.sector_temp_detail[sector]["stocks"].append(r.get("symbol", ""))
        
        for sec, info in self.sector_temp_detail.items():
            info["avg_chg"] = round(info["avg_chg"] / info["count"], 2) if info["count"] else 0
            if info["avg_chg"] > 2:
                self.sector_temp_counts["热"] += 1
            elif info["avg_chg"] > 0.5:
                self.sector_temp_counts["温"] += 1
            elif info["avg_chg"] > -0.5:
                self.sector_temp_counts["平"] += 1
            else:
                self.sector_temp_counts["凉"] += 1
    
    # ═══ LDS双门状态（宏观 × 趋势） ═══
    def _calc_dual_gate(self):
        md = self.macro_data
        cpi = md.get("cpi")
        pmi = md.get("pmi")
        if cpi is None or pmi is None:
            self.dual_gate = {"macro_gate": "数据缺失", "trend_gate": "未知", "action": "hold", "detail": "宏观数据不完整"}
            self.dual_action = "hold"
            self.dual_detail = "宏观数据不完整，维持现有仓位"
            return
        
        # 宏观门：CPI<2 + PMI≥50 = 绿灯；CPI≥2.5 = 红灯
        if cpi < 1.0:
            macro_gate = "黄灯"  # 通缩风险，谨慎
            macro_detail = f"CPI{cpi}%<1%，通缩风险，降息空间有限"
        elif cpi < 2.0:
            macro_gate = "绿灯"
            macro_detail = f"CPI{cpi}%，无通胀压力"
        elif cpi < 3.0:
            macro_gate = "黄灯"
            macro_detail = f"CPI{cpi}%≥2%，通胀抬头"
        else:
            macro_gate = "红灯"
            macro_detail = f"CPI{cpi}%≥3%，高通胀杀估值"
        
        if pmi < 48:
            if macro_gate == "绿灯": macro_gate = "黄灯"
            macro_detail += f"，PMI{pmi}<48收缩"
        
        # 趋势门：凉→平→温→热，当前周期位置
        t = self.trend_temp
        trend_gate_map = {"凉": "红灯", "平": "黄灯", "温": "绿灯", "热": "绿灯"}
        trend_gate = trend_gate_map.get(t, "黄灯")
        
        # 双门组合 → 操作方向
        gate_combo = f"{macro_gate}+{trend_gate}"
        dual_map = {
            "绿灯+绿灯": ("右侧追涨", "宏观宽松+趋势向上，全仓右侧"),         # 宏观+趋势都好
            "绿灯+黄灯": ("右侧谨慎", "宏观好但趋势平，等趋势转温再右侧"),     # 转暖等信号
            "绿灯+红灯": ("左侧低吸", "宏观好但趋势凉，布局基本面优质票"),     # 左侧布局
            "黄灯+绿灯": ("右侧谨慎", "趋势好但宏观有隐忧，控制仓位右侧"),     # LDS: 趋势>宏观但谨慎
            "黄灯+黄灯": ("观望为主", "宏观趋势都不明朗，轻仓试错"),          # 
            "黄灯+红灯": ("左侧试探", "趋势凉+宏观一般，极小仓位左侧"),       # 
            "红灯+绿灯": ("右侧减仓", "宏观警报但趋势还在，减仓保利润"),      # 
            "红灯+黄灯": ("减仓观望", "宏观红灯+趋势平，逐步出清"),           # LDS说清仓
            "红灯+红灯": ("空仓等待", "宏观趋势双杀，关仓不玩"),             # LDS说的关仓
        }
        self.dual_action, self.dual_detail = dual_map.get(gate_combo, ("观望", "无法判断"))
        
        self.dual_gate = {
            "macro_gate": macro_gate,
            "macro_detail": macro_detail,
            "trend_gate": trend_gate,
            "trend_phase": t,
            "combo": gate_combo,
            "action": self.dual_action,
            "detail": self.dual_detail,
        }

    # ═══ ③ 因子权重（宏观状态→权重映射） ═══
    def _calc_factor_weights(self):
        r = self.regime
        self.factor_weights = config.FACTOR_WEIGHTS.get(r, config.FACTOR_WEIGHTS["default"])

    def get_factor_weights(self):
        return self.factor_weights

    # ═══ ④ CPI驱动策略开关（LDS核心） ═══
    def _calc_strategy_switch(self):
        md = self.macro_data
        cpi = md.get("cpi")

        if cpi is not None:
            if cpi < 1.0:
                mapping = config.CPI_STRATEGY_MAP["cpi_falling_below1"]
            elif cpi < 2.0:
                mapping = config.CPI_STRATEGY_MAP["cpi_1_to_2"]
            elif cpi < 3.0:
                mapping = config.CPI_STRATEGY_MAP["cpi_2_to_3"]
            else:
                mapping = config.CPI_STRATEGY_MAP["cpi_above3"]
        else:
            mapping = config.CPI_STRATEGY_MAP["default"]

        self.strategy_switch = mapping["switch"]
        self.strategy_reason = mapping["reason"]
        self.cpi_caption = mapping["caption"]

        # 趋势温度修正（LDS：趋势>CPI）
        if self.trend_temp == "凉" and self.strategy_switch == "on":
            self.strategy_switch = "limited"
            self.strategy_reason += " + 趋势偏凉"

    # ═══ ⑤ 总仓位估算 ═══
    def _calc_position(self):
        # 基准
        base = {"on": 0.7, "limited": 0.4, "off": 0.05}.get(self.strategy_switch, 0.5)

        # 趋势修正
        temp_adjust = {"热": -0.2, "温": 0.0, "平": 0.0, "凉": -0.15}.get(self.trend_temp, 0)

        self.suggested_position = max(0.05, min(0.85, base + temp_adjust))

    def suggest_total_position(self) -> float:
        return self.suggested_position

    # ═══ 输出 ═══
    def summarize(self) -> dict:
        t = self.trend_temp
        trend_info = config.TREND_TEMP.get(t, {"max_deviation": 0.05, "action": "中性操作"})

        return {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "quadrant": self.quadrant,
            "regime": self.regime,
            "trend_temp": t,
            "trend_action": trend_info["action"],
            "strategy_switch": self.strategy_switch,
            "strategy_reason": getattr(self, "strategy_reason", ""),
            "factor_weights": self.factor_weights,
            "suggested_position": round(self.suggested_position, 2),
            "macro_data": {k: v for k, v in self.macro_data.items()
                          if k in ("cpi", "pmi", "m2_growth", "shibor", "cny_usd",
                                   "cpi_trend", "pmi_trend", "cpi_date", "pmi_date")},
            "guoyun": {
                "price": self.guoyun_price,
                "deviation": self.price_deviation,
                "note": self.guoyun_note,
            },
            "dual_gate": getattr(self, "dual_gate", {}),
            "sector_temp": getattr(self, "sector_temp_counts", {}),
            "market": getattr(self, "_market_overview", {}),
            "macro_data_ok": self.macro_data_ok,
            "warnings": self.macro_warnings,
        }


if __name__ == "__main__":
    me = MacroEngine()
    s = me.refresh()
    import json
    print(json.dumps(s, ensure_ascii=False, indent=2))
