"""数据级验证 v2: 同链多标的 → 截面标准化有区分度, composite 非全 0.5"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.factor_engine import FactorEngine

engine = FactorEngine()
# 食品饮料链 4 只 + 新能源 2 只 (同链 ≥2 才有截面区分)
symbols = ["600519", "000858", "000568", "600809", "300750", "002594"]
print(f"=== score_batch {len(symbols)} 标的 (线程池 + baostock 修复后) ===")
result = engine.score_batch(symbols, macro_state="扩张期")
for r in result:
    sc = r["scores"]
    n_neutral = sum(1 for v in sc.values() if abs(v - 0.5) < 0.001)
    print(f"  {r['symbol']:8s} composite={r['composite']:.3f}  中性风格数={n_neutral}/9  chain={r.get('chain')}")
print("\n=== 判定: composite 非全同值 + 中性风格 < 9/9 = 数据通道已恢复 ===")