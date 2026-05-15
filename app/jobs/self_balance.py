from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class BalanceEntry:
    dominant_persona: str
    dominant_component: str  # base_personality | offline_life | observed_info | post_content
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SelfBalanceTracker:
    """Tracks recent reply decisions to prevent repetitive response patterns.

    In-memory per-agent storage. One tracker per agent lifecycle (resets on wake).
    """

    _stores: dict[str, "SelfBalanceTracker"] = {}

    def __init__(self, window_size: int = 10) -> None:
        self.window_size: int = window_size
        self.history: list[BalanceEntry] = []

    @classmethod
    def for_agent(cls, agent_id: str, window_size: int = 10) -> "SelfBalanceTracker":
        if agent_id not in cls._stores:
            cls._stores[agent_id] = cls(window_size)
        return cls._stores[agent_id]

    def record_decision(self, dominant_persona: str, dominant_component: str) -> None:
        self.history.append(BalanceEntry(
            dominant_persona=dominant_persona,
            dominant_component=dominant_component,
        ))
        if len(self.history) > self.window_size:
            self.history = self.history[-self.window_size:]

    def get_component_distribution(self) -> dict[str, float]:
        if not self.history:
            return {"base_personality": 0.25, "offline_life": 0.25,
                    "observed_info": 0.25, "post_content": 0.25}
        counter = Counter(e.dominant_component for e in self.history)
        total = len(self.history)
        return {k: v / total for k, v in counter.items()}

    def compute_hunger(self, component: str) -> float:
        """Low frequency in window → high hunger (> 0.5 means hungry)."""
        dist = self.get_component_distribution()
        freq = dist.get(component, 0.0)
        return 1.0 - freq

    def compute_saturation(self, component: str) -> float:
        """High frequency in window → high saturation (> 0.7 means over-saturated)."""
        dist = self.get_component_distribution()
        return dist.get(component, 0.0)

    def check_diversity(self, persona: str, max_consecutive: int = 3) -> bool:
        """Return False if same persona appeared >= max_consecutive times consecutively."""
        if len(self.history) < max_consecutive:
            return True
        recent = self.history[-max_consecutive:]
        return not all(e.dominant_persona == persona for e in recent)
