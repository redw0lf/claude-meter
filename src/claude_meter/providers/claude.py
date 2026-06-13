"""Claude provider: wraps usage.py."""
from __future__ import annotations

from claude_meter.providers import ServiceCard
from claude_meter.usage import extract, fetch_usage


class ClaudeProvider:
    def fetch(self) -> ServiceCard:
        data = fetch_usage()
        five_pct, five_reset, week_pct, week_reset = extract(data)
        return ServiceCard(
            title="Claude",
            row1_label="5h",
            row1_pct=five_pct,
            row1_note=five_reset,
            row2_label="7d",
            row2_pct=week_pct,
            row2_note=week_reset,
        )
