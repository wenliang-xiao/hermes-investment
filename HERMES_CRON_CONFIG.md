# Hermes Cron 时间更新说明

## 需要在 ECS 上执行的操作

登录 ECS 后找到 Hermes 的 skill YAML 文件，通常在：
```
/home/admin/.hermes/skills/
```

### 新的 cron 时间表

| 任务 | 脚本 | 时间 | 说明 |
|---|---|---|---|
| 早盘前决策简报 | `run_daily.py` | 工作日 08:30 | 开盘前5分钟读完 |
| 收盘后复盘简报 | `run_daily.py` | 工作日 18:00 | 收盘后回顾 |
| 周报+15链研究 | `run_weekly.py` | 周日 18:00 | 含链内候选扫描 |
| 按需深度研报 | `run_research.py --symbol <代码>` | Hermes触发 | 单股深度 |

### 如果使用 Hermes YAML skill 文件，格式参考：

```yaml
name: investment_daily_morning
description: 每日开盘前决策简报
schedule: "30 8 * * 1-5"  # 周一至周五 08:30
command: python /home/admin/.hermes/investment_system/scripts/run_daily.py

---

name: investment_daily_evening
description: 每日收盘后复盘简报
schedule: "0 18 * * 1-5"  # 周一至周五 18:00
command: python /home/admin/.hermes/investment_system/scripts/run_daily.py

---

name: investment_weekly
description: 周报+15链深度研究+候选扫描
schedule: "0 18 * * 0"  # 每周日 18:00
command: python /home/admin/.hermes/investment_system/scripts/run_weekly.py
```

### 旧的入口（保持兼容，可以继续用）

旧的 `run_report_v7.py` 和 `run_report_v8.py` 仍然存在，不影响。
如果 Hermes 里已经配置了这两个脚本的 cron，建议：
1. 保留 `run_report_v8.py` 的 cron（兜底用）
2. 新增 `run_daily.py` 的两个时间点
3. 新增 `run_weekly.py` 的周日时间点
4. 逐步停用 `run_report_v7.py`（周报功能已被 run_weekly.py 覆盖）
