"""Service providers: fetch usage data and return a ServiceCard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from claude_meter.config import Config


@dataclass
class ServiceCard:
    title:      str    # shown on-screen, e.g. "Claude"
    row1_label: str    # e.g. "5h", "seats"
    row1_pct:   float  # 0‒100+ (bar clamps to 100)
    row1_note:  str    # e.g. "in 2h", "active"
    row2_label: str
    row2_pct:   float
    row2_note:  str


class Provider(Protocol):
    def fetch(self) -> ServiceCard: ...


def get(name: str, cfg: "Config") -> Provider:
    if name == "claude":
        from claude_meter.providers.claude import ClaudeProvider
        return ClaudeProvider()
    if name == "copilot":
        from claude_meter.providers.copilot import CopilotProvider
        return CopilotProvider(token=cfg.github_token, org=cfg.copilot_org)
    raise ValueError(f"unknown provider: {name!r}")
