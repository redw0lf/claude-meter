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


def get_all(cfg: Config) -> list[Provider]:
    """Expand cfg.services into a flat list of Provider instances.

    "copilot" expands to one provider per entry in cfg.copilot_orgs, or a
    single individual-mode provider when the list is empty.
    """
    from claude_meter.providers.claude import ClaudeProvider
    from claude_meter.providers.copilot import CopilotProvider

    result: list[Provider] = []
    for svc in cfg.services:
        if svc == "claude":
            result.append(ClaudeProvider())
        elif svc == "copilot":
            orgs = cfg.copilot_orgs or [""]   # "" = individual subscription
            for org in orgs:
                result.append(CopilotProvider(token=cfg.github_token, org=org))
        else:
            raise ValueError(f"unknown provider: {svc!r}")
    return result
