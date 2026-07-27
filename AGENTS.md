# 面基投资系统 - 开发规范（AGENTS.md）

## 核心开发原则

### 1. 数据源可靠性是第一优先级
- **数据质量决定找票能力** — 多因子模型的精度被数据源可靠性限制
- **优先级链**: 券商专业API(K线/财务) → 腾讯实时行情(保留) → baostock(兜底) → akshare(降级)
- 蜻蜓CSC Skill: 财报T+2~3h, 行业排名日频, 仅A股
- Tencent qt.gtimg: 实时行情, 偶尔封IP
- 港股/美股: yfinance (无A股替代)

### 2. 开发流程
- **WS0先行** — 任何改动前先确认: API可用? 数据结构正确? Git基线?
- **Fix > Feature** — 修已知bug永远在加新功能之前
- **TDD** — 先写测试(FAIL) → 实现(PASS) → 重构
- **原子提交** — 每个WS一个commit, commit即推
- 大幅改动 → 飞书文档评审 → 评论共识 → 实施

### 3. 代码质量控制
- **类型提示**: 所有新函数必须带类型注解
- **错误处理**: 每个外部调用必须 try/except + fallback 链
- **日志**: 关键节点必须 logging.info/warning
- **缓存**: 财务数据同进程内缓存, 行情数据每次调用刷新
- **限频**: 批量调用必须加 time.sleep 间隔

### 4. 因子引擎架构规则
- **三层分离**: Layer3(数据映射) → Layer2(截面标准化) → Layer1(风格聚合)
- **截面百分位排序** — 不固定区间映射, 真 percent_rank
- **多维输出** — 不单值, 输出子因子/风格因子/IC权重等全维度
- **IC滚动权重** — weight = recent_ic / sum(recent_ic), 不回看模型
- **数据质量追踪** — 每个因子附 data_quality 字段

### 5. WATCHLIST 规范
- **动态 + 深度精选** — 白名单是经过深度分析的自选, 不是机械扫描
- 按链(chain)分类归类, 买卖逻辑必须自洽
- IPO发现: 蜻蜓全A股 → 按市值/流动性筛选 → 人工判断纳入

### 6. 因子定义规范
- 因子定义在 SUB_FACTOR_DEFS dict 中, 含 source/field/higher_is_better/label
- source: fin_report(财务) / daily_row(日线) / derived(计算)
- 新因子: 加 SUB_FACTOR_DEFS + STYLE_FACTORS + 数据层管道

### 7. 特殊风险考量
- **打新/IPO**: PE虚高风险, 股东结构风险(政府股东→城投债隐患)
- **行业非理性**: 光模块/存储等行业的情绪高涨, 需加入 sentiment 行业维度
- **监管风险**: 老虎/富途监管变化等事件驱动

### 8. 多券商Skill体系
```
蜻蜓CSC (已接入) → 财报/行业排名/ETF
灵犀Skills (待接入) → 研报/行情
华泰智研 (待接入) → 行业观点/估值
ima广场 (待接入) → 股票信息/财务对比
CICC Skills (待接入) → 分析师研究
```

## 数据源配置

```bash
# 蜻蜓 CSC API
export CSC_API_KEY="shk_xxxxxxxxxxxxxx"
export CSC_BASE_URL="https://skillhub.csc108.com/api/skillhub/v1"

# 或使用遗留文件
# ~/.hermes/.env.dragonfly: DRAGONFLY_API_KEY=shk_xxx
```

## 模块地图

```
data/
  data_layer.py        # 统一数据入口 (get_financial_report/get_history)
  data_router.py       # 行情路由 (Tencent/baostock)
  sources/
    qingting_source.py # 蜻蜓CSC API封装 (2026-07-27新增)
    baostock_source.py
    akshare_source.py
    yahoo_source.py
engine/
  factor_engine.py     # v4.0 因子引擎 (19子7风格)
  factor_scanner.py    # v3.1 (deprecated)
  evidence_builder.py  # 证据链构建
  signal_validator.py  # 信号验证
scripts/
  run_factor_daily.py  # 因子日更
  run_trading.py       # 交易执行
  run_daily.py         # 日报管线
```

## 联系方式
- GitHub: wenliang-xiao/hermes-investment
- 日报推送: 飞书「知行合一」群
-  Dashboard: http://47.85.161.255/dashboard
