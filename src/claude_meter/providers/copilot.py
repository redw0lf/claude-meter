"""GitHub Copilot provider.

Two modes depending on whether `copilot_org` is set:

Individual (no org)
  GET /user/copilot_billing
  row1 = seat active (100 / 0), row2 = IDE chat enabled (100 / 0)

Org plan
  GET /orgs/{org}/copilot/billing  — seat utilization
  GET /orgs/{org}/copilot/usage    — 28-day acceptance rate
  row1 = acceptance rate %, row2 = seat utilization %

Requires a GitHub PAT with the `manage_billing:copilot` scope (org plan)
or `read:user` (individual).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from claude_meter.providers import ServiceCard

_GH_API = "https://api.github.com"


def _gh_get(path: str, token: str) -> dict | list:
    req = urllib.request.Request(
        f"{_GH_API}{path}",
        headers={
            "Authorization": f"token {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        },
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


class CopilotProvider:
    def __init__(self, token: str, org: str = ""):
        if not token:
            raise ValueError(
                "github_token is required for the Copilot provider. "
                "Run: claude-meter configure --github-token <PAT>"
            )
        self._token = token
        self._org   = org

    def fetch(self) -> ServiceCard:
        if self._org:
            return self._fetch_org()
        return self._fetch_individual()

    def _fetch_individual(self) -> ServiceCard:
        try:
            data = _gh_get("/user/copilot_billing", self._token)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ServiceCard(
                    title="Copilot",
                    row1_label="seat", row1_pct=0.0, row1_note="no subscription",
                    row2_label="chat", row2_pct=0.0, row2_note="—",
                )
            raise

        seats      = data.get("seat_breakdown", {}) if isinstance(data, dict) else {}
        active     = seats.get("active_this_cycle", 0) or 0
        seat_pct   = 100.0 if active > 0 else 0.0
        seat_note  = "active" if active > 0 else "inactive"

        ide_chat   = (data.get("ide_chat") or "") if isinstance(data, dict) else ""
        chat_pct   = 100.0 if ide_chat == "enabled" else 0.0
        chat_note  = "on" if chat_pct == 100.0 else "off"

        return ServiceCard(
            title="Copilot",
            row1_label="seat", row1_pct=seat_pct, row1_note=seat_note,
            row2_label="chat", row2_pct=chat_pct, row2_note=chat_note,
        )

    def _fetch_org(self) -> ServiceCard:
        billing = _gh_get(f"/orgs/{self._org}/copilot/billing", self._token)
        seats   = (billing.get("seat_breakdown") or {}) if isinstance(billing, dict) else {}
        total   = seats.get("total", 0) or 0
        active  = seats.get("active_this_cycle", 0) or 0
        seat_pct  = (active / total * 100) if total > 0 else 0.0
        seat_note = f"{active}/{total}"

        usage_list = _gh_get(
            f"/orgs/{self._org}/copilot/usage?per_page=28", self._token
        )
        if isinstance(usage_list, list) and usage_list:
            total_sugg = sum(d.get("total_suggestions_count", 0) for d in usage_list)
            total_acc  = sum(d.get("total_acceptances_count",  0) for d in usage_list)
            acc_pct    = (total_acc / total_sugg * 100) if total_sugg > 0 else 0.0
            acc_note   = f"{total_acc}/{total_sugg}"
        else:
            acc_pct  = 0.0
            acc_note = "no data"

        return ServiceCard(
            title=f"Copilot/{self._org}",
            row1_label="accept", row1_pct=acc_pct,  row1_note=acc_note,
            row2_label="seats",  row2_pct=seat_pct, row2_note=seat_note,
        )
