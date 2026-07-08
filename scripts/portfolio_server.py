#!/usr/bin/env python3
"""面基投资模拟盘 — 专业数据面板服务器 (Bridge)

启动:
  uvicorn scripts.portfolio_server:app --host 0.0.0.0 --port 8686
  python3 scripts/portfolio_server.py 8686
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.server import app

if __name__ == "__main__":
    import uvicorn
    import sys as _sys
    port = int(_sys.argv[1]) if len(_sys.argv) > 1 else 8686
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")