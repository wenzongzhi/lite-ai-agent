"""Thread-safe, non-secret runtime controls shared by CLI and requests."""

import math
from dataclasses import dataclass, replace
from threading import RLock

from config import AgentSettings, FeatureSettings, Settings


@dataclass(frozen=True)
class RuntimeSnapshot:
    features: FeatureSettings
    agent: AgentSettings
    doubao_model: str
    fast_reply_timeout_seconds: float
    web_search_enabled: bool
    web_search_max_results: int


class RuntimeState:
    def __init__(self, settings: Settings):
        self._lock = RLock()
        self.reload(settings)

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return self._snapshot

    def reload(self, settings: Settings):
        with self._lock:
            self._snapshot = RuntimeSnapshot(settings.features, settings.agent, settings.doubao.model,
                settings.server.fast_reply_timeout_seconds, settings.web_search.enabled,
                settings.web_search.max_results)

    def set_feature(self, feature: str, enabled: bool):
        if feature not in ("ai-answer", "ai-agent"):
            raise ValueError("Unknown feature")
        with self._lock:
            features = replace(self._snapshot.features, **{feature.replace("-", "_") + "_enabled": enabled})
            self._snapshot = replace(self._snapshot, features=features)

    def set_model(self, model: str):
        if not model.strip() or len(model) > 200:
            raise ValueError("Invalid model ID")
        with self._lock:
            self._snapshot = replace(self._snapshot, doubao_model=model.strip())

    def set_fast_timeout(self, seconds: float):
        if not math.isfinite(seconds) or not 0 < seconds <= 120:
            raise ValueError("fast-timeout must be greater than 0 and at most 120 seconds")
        with self._lock:
            self._snapshot = replace(self._snapshot, fast_reply_timeout_seconds=seconds)
