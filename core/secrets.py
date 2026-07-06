import os
from pathlib import Path

BASE = Path(os.environ.get("HERMES_BASE", "/home/admin/.hermes/investment_system"))
DATA_DIR = BASE / "data"
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    pass

JQDATA_USER = os.environ.get("JQDATA_USER", "")
JQDATA_PASS = os.environ.get("JQDATA_PASS", "")

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")

FEISHU_TOOL = os.environ.get("FEISHU_TOOL", "/home/admin/.hermes/node_modules/.bin/feishu-tool")
FEISHU_FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "QhIOfB63Sl6Kqmd81fycjR6jnDd")
FEISHU_USER_OPENID = os.environ.get("FEISHU_USER_OPENID", "ou_e03d56632de9b44263adfc018f9d6e4d")
FEISHU_GROUP_CHAT = os.environ.get("FEISHU_GROUP_CHAT", "oc_4c9d6445fab7f3a2ada0c410f3aa7043")
