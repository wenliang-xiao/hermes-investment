from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class DataSource(ABC):

    name: str = ""
    priority: int = 99

    @abstractmethod
    def is_available(self) -> bool: ...

    def get_daily_bars(self, symbol: str, count: int = 60) -> Optional[Any]:
        return None

    def get_financial(self, symbol: str) -> Optional[Dict[str, Any]]:
        return None

    def get_macro(self) -> Optional[Dict[str, Any]]:
        return None
