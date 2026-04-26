"""
策略基类 — 所有量化策略继承于此

用法:
    class MyStrategy(BaseStrategy):
        @property
        def name(self): return "my_strat"
        
        def generate_signals(self, df):
            # 返回信号: 1=做多, -1=做空, 0=持有
            ...
"""

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
import json
import yaml
import logging

logger = logging.getLogger("quant.strategy")

_CONFIG_PATH = Path(__file__).parent.parent / "config/config.yaml"
with open(_CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)


@dataclass
class Signal:
    """交易信号"""
    ticker: str
    direction: int        # 1 = long, -1 = short, 0 = close
    confidence: float      # 0.0 ~ 1.0
    timestamp: pd.Timestamp
    metadata: dict = field(default_factory=dict)


@dataclass
class TradeRecord:
    """成交记录"""
    ticker: str
    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp] = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    direction: int = 1      # 1=long, -1=short
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""


class BaseStrategy(ABC):
    """所有策略的基类"""

    def __init__(self, params: dict = None):
        self.params = params or {}
        self.signals: List[Signal] = []
        self.trades: List[TradeRecord] = []
        self.position = 0  # 当前持仓方向
        self._name = self.__class__.__name__

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        生成信号序列
        返回: pd.Series, index=时间, values=[1, 0, -1]
        """
        pass

    def on_data(self, df: pd.DataFrame) -> List[Signal]:
        """新的数据到来时触发"""
        sig_series = self.generate_signals(df)
        signals = []
        for idx in range(len(sig_series)):
            if sig_series.iloc[idx] != 0 and sig_series.iloc[idx] != self.position:
                sig = Signal(
                    ticker="",
                    direction=int(sig_series.iloc[idx]),
                    confidence=abs(sig_series.iloc[idx]),
                    timestamp=sig_series.index[idx],
                )
                signals.append(sig)
                self.position = sig.direction
        self.signals.extend(signals)
        return signals

    def save_state(self, path: str = None):
        """保存策略状态"""
        if path is None:
            path = str(Path(__file__).parent.parent / f"strategies/{self.name}_state.json")
        state = {
            "name": self.name,
            "params": self.params,
            "position": self.position,
            "timestamp": pd.Timestamp.now().isoformat(),
        }
        with open(path, "w") as f:
            json.dump(state, f, indent=2)

    def load_state(self, path: str = None):
        """加载策略状态"""
        if path is None:
            path = str(Path(__file__).parent.parent / f"strategies/{self.name}_state.json")
        p = Path(path)
        if p.exists():
            with open(p) as f:
                state = json.load(f)
            self.params = state.get("params", {})
            self.position = state.get("position", 0)
