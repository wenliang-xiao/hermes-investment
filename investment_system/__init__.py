"""investment_system 兼容包 — 生产环境项目根目录名。

生产环境把项目内容放在 `investment_system/` 目录下（import 路径为
`investment_system.data.data_layer` 等），本地开发环境直接把内容放在仓库根目录
（import 路径为 `data.data_layer`）。本文件把 `investment_system.xxx` 别名到 `xxx`，
让生产环境的 import 路径在本地/非包目录部署时也能工作。
"""
import sys as _sys
import importlib as _importlib

_SUBMODULES = [
    "config", "data", "domain", "analysis", "output", "scripts",
    "engine", "etf", "core", "dashboard",
]

for _name in _SUBMODULES:
    try:
        _mod = _importlib.import_module(_name)
        _sys.modules[f"investment_system.{_name}"] = _mod
    except ImportError:
        pass
