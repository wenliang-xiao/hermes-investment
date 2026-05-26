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
