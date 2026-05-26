"""
Core base classes and canonical data models for the investment system.
v4.0 — plugin-oriented architecture
"""
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List


@dataclass
class AssetSnapshot:
    """Unified representation of a single asset's current state."""
    symbol: str
    name: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[float] = None
    rsi: Optional[float] = None
    ma60_dev: Optional[float] = None
    tech_score: Optional[float] = None
    badges: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MacroState:
    """Output of macro analysis — the regime and gate signals."""
    regime: str = "default"
    dual_gate: Dict[str, Any] = field(default_factory=dict)
    macro_data: Dict[str, Any] = field(default_factory=dict)
    favored_sectors: List[str] = field(default_factory=list)
    avoided_sectors: List[str] = field(default_factory=list)
    trend_temp: str = "平"
    macro_warnings: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)  # original dict for backward compat


@dataclass
class ResearchContext:
    """Input context for deep research on a single stock."""
    symbol: str
    name: str
    macro_state: Optional[MacroState] = None
    chain: str = ""
    focus: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Output of a single analysis module."""
    module: str
    data: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    ok: bool = True


@dataclass
class ReportDocument:
    """Represents a Feishu document being built."""
    doc_id: str
    title: str
    sections: List[str] = field(default_factory=list)
