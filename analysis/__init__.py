"""
analysis/ — Backward-Compatibility Bridge

All modules in this directory are thin re-exports pointing to their
new locations in engine/, etf/, research/, or _archive/.

For new code, import from the new locations directly:
    from engine.factor_engine import FactorEngine
    from etf.etf_portfolio import EtfPortfolioBuilder
    from research.decoupling_discovery import get_discovered_stocks

This directory is kept only for backward compatibility with old import paths.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import AnalysisResult


class AnalysisModule(ABC):

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, context: Dict[str, Any]) -> AnalysisResult: ...

    def is_available(self) -> bool:
        return True
