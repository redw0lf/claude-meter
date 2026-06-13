"""GitHub Copilot provider.

Three modes controlled by the slug and api_level:

Individual (slug="")
  GET /user/copilot_billing
  row1 = seat active (100 / 0), row2 = IDE chat enabled (100 / 0)

Org (api_level="org")
  GET /orgs/{slug}/copilot/metrics/reports/organization-28-day/latest
    → download_links[] → parse report for acceptance rate
  GET /orgs/{slug}/copilot/billing
    → seat utilization

Enterprise (api_level="enterprise")
  GET /enterprises/{slug}/copilot/metrics/reports/enterprise-28-day/latest
    → download_links[] → parse report for acceptance rate
  GET /enterprises/{slug}/copilot/billing
    → seat utilization

The metrics report endpoints require API version 2026-03-10. Each response
contains signed download URLs. The actual file format (CSV / JSON / NDJSON)
is not documented; this module auto-detects it. If unknown fields are
encountered, a ValueError is raised with the available field names so the
caller can diagnose and fix the field mapping.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.request

from claude_meter.providers import ServiceCard

_GH_API        = "https://api.github.com"
_API_STABLE    = "2022-11-28"
_API_METRICS   = "2026-03-10"

# Field name candidates for suggestions / acceptances across API versions.
_SUGG_FIELDS = ("total_suggestions_count", "total_suggestions", "suggestions")
_ACC_FIELDS  = ("total_acceptances_count", "total_acceptances", "acceptances")


def _gh_get(path: str, token: str, api_version: str = _API_STABLE) -> dict | list:
    req = urllib.request.Request(
        f"{_GH_API}{path}",
        headers={
            "Authorization": f"token {token}",
            "X-GitHub-Api-Version": api_version,
            "Accept": "application/vnd.github+json",
        },
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _download(url: str) -> list[dict]:
    """Fetch a signed report URL and return it as a list of row dicts.

    Auto-detects JSON array, newline-delimited JSON, and CSV.
    """
    raw = urllib.request.urlopen(url, timeout=30).read()
    text = raw.decode("utf-8", errors="replace")

    # Try JSON array / object.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Try newline-delimited JSON.
    rows: list[dict] = []
    all_ndjson = True
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            all_ndjson = False
            break
    if all_ndjson and rows:
        return rows

    # Fall back to CSV.
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _sum_field(rows: list[dict], *candidates: str) -> int | None:
    """Sum the first matching candidate field across all rows.

    Returns None if no candidate is found in any row (signals unknown schema).
    """
    found_field: str | None = None
    for row in rows:
        for candidate in candidates:
            if candidate in row:
                found_field = candidate
                break
        if found_field:
            break
    if found_field is None:
        return None
    total = 0
    for row in rows:
        try:
            total += int(row.get(found_field) or 0)
        except (ValueError, TypeError):
            pass
    return total


class CopilotProvider:
    def __init__(self, token: str, org: str = "", level: str = "org"):
        if not token:
            raise ValueError(
                "github_token is required for the Copilot provider. "
                "Run: claude-meter configure --github-token <PAT>"
            )
        self._token = token
        self._org   = org
        self._level = level   # "org" or "enterprise"

    @property
    def _prefix(self) -> str:
        if self._level == "org":
            return f"/orgs/{self._org}"
        return f"/enterprises/{self._org}"

    @property
    def _report_type(self) -> str:
        if self._level == "org":
            return "organization-28-day"
        return "enterprise-28-day"

    def fetch(self) -> ServiceCard:
        if self._org:
            return self._fetch_account()
        return self._fetch_individual()

    # ------------------------------------------------------------------
    # Individual subscription
    # ------------------------------------------------------------------

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

        seats     = data.get("seat_breakdown", {}) if isinstance(data, dict) else {}
        active    = seats.get("active_this_cycle", 0) or 0
        seat_pct  = 100.0 if active > 0 else 0.0
        seat_note = "active" if active > 0 else "inactive"

        ide_chat  = (data.get("ide_chat") or "") if isinstance(data, dict) else ""
        chat_pct  = 100.0 if ide_chat == "enabled" else 0.0
        chat_note = "on" if chat_pct == 100.0 else "off"

        return ServiceCard(
            title="Copilot",
            row1_label="seat", row1_pct=seat_pct, row1_note=seat_note,
            row2_label="chat", row2_pct=chat_pct, row2_note=chat_note,
        )

    # ------------------------------------------------------------------
    # Org / enterprise
    # ------------------------------------------------------------------

    def _fetch_account(self) -> ServiceCard:
        acc_pct, acc_note = self._fetch_acceptance()
        seat_pct, seat_note = self._fetch_seats()

        return ServiceCard(
            title=f"Copilot/{self._org}",
            row1_label="accept", row1_pct=acc_pct,  row1_note=acc_note,
            row2_label="seats",  row2_pct=seat_pct, row2_note=seat_note,
        )

    def _fetch_acceptance(self) -> tuple[float, str]:
        """Fetch 28-day acceptance rate via the 2026-03-10 metrics reports API."""
        endpoint = (
            f"{self._prefix}/copilot/metrics/reports"
            f"/{self._report_type}/latest"
        )
        try:
            meta = _gh_get(endpoint, self._token, api_version=_API_METRICS)
        except urllib.error.HTTPError as e:
            if e.code in (204, 404):
                return 0.0, "no data"
            raise

        links = (meta.get("download_links") or []) if isinstance(meta, dict) else []
        if not links:
            return 0.0, "no data"

        # Aggregate across all download parts (reports may be sharded).
        all_rows: list[dict] = []
        for url in links:
            all_rows.extend(_download(url))

        if not all_rows:
            return 0.0, "no data"

        total_sugg = _sum_field(all_rows, *_SUGG_FIELDS)
        total_acc  = _sum_field(all_rows, *_ACC_FIELDS)

        if total_sugg is None or total_acc is None:
            available = sorted(all_rows[0].keys()) if all_rows else []
            raise ValueError(
                f"Copilot metrics report has unknown schema. "
                f"Available fields: {available}"
            )

        if total_sugg == 0:
            return 0.0, "0 suggestions"

        pct  = total_acc / total_sugg * 100
        note = f"{total_acc}/{total_sugg}"
        return pct, note

    def _fetch_seats(self) -> tuple[float, str]:
        """Fetch seat utilization from the billing endpoint."""
        try:
            billing = _gh_get(f"{self._prefix}/copilot/billing", self._token)
        except urllib.error.HTTPError as e:
            if e.code in (404, 403):
                return 0.0, "n/a"
            raise
        seats     = (billing.get("seat_breakdown") or {}) if isinstance(billing, dict) else {}
        total     = seats.get("total", 0) or 0
        active    = seats.get("active_this_cycle", 0) or 0
        seat_pct  = (active / total * 100) if total > 0 else 0.0
        seat_note = f"{active}/{total}"
        return seat_pct, seat_note
