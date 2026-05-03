"""Surface publique pour la métrologie (prompt §8).

Re-exporte ``MetricsCollector`` et ``PollingMetrics`` depuis le module historique
``services.metrics_collector`` pour respecter la nomenclature du prompt sans
casser les imports déjà en place.
"""
from __future__ import annotations

from services.metrics_collector import MetricsCollector, PollingMetrics

__all__ = ["MetricsCollector", "PollingMetrics"]
