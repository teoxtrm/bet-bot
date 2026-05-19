"""
Data Source Health Tracking
============================
Every tip and watchlist entry carries a `data_flags` dict that records
which sources were available when the pick was generated.

Status values:
  "ok"      — data fetched successfully
  "missing" — source returned nothing (no Pinnacle line, no form data, etc.)
  "failed"  — source threw an error (network, HTTP error, parse failure)
  "stale"   — data served from cache older than today

Critical sources (Pinnacle odds): if missing → confidence is unreliable,
the tip is demoted rather than silently shown.

Optional sources (team form, league stats): if missing → tip is shown
with a ⚠️ warning so the user knows it was built on partial data.
"""

from dataclasses import dataclass, field


# Sources classified by importance
_CRITICAL = {"pinnacle", "odds_api"}
_OPTIONAL = {"team_form", "league_stats", "fBref"}


@dataclass
class SourceResult:
    source:     str
    status:     str        # "ok" | "missing" | "failed" | "stale"
    error:      str = ""
    note:       str = ""   # human-readable detail shown in UI tooltip


class EventHealth:
    """
    Collects data source results for a single scanned event.
    Attach .flags() to each _evdata entry so tips and watchlist
    entries carry full provenance.
    """

    def __init__(self):
        self._results: dict[str, SourceResult] = {}

    # ── Recording helpers ─────────────────────────────────────────────────────

    def ok(self, source: str, note: str = ""):
        self._results[source] = SourceResult(source, "ok", note=note)

    def missing(self, source: str, note: str = ""):
        self._results[source] = SourceResult(source, "missing", note=note)

    def failed(self, source: str, error: str = "", note: str = ""):
        self._results[source] = SourceResult(source, "failed", error=error, note=note)

    def stale(self, source: str, note: str = ""):
        self._results[source] = SourceResult(source, "stale", note=note)

    # ── Derived state ─────────────────────────────────────────────────────────

    def flags(self) -> dict[str, str]:
        """Flat {source: status} dict — stored on every tip/watchlist entry."""
        return {s: r.status for s, r in self._results.items()}

    def is_critical_ok(self) -> bool:
        """False if any critical source (Pinnacle) is missing/failed."""
        for src in _CRITICAL:
            r = self._results.get(src)
            if r and r.status not in ("ok", "stale"):
                return False
        return True

    def has_warnings(self) -> bool:
        return any(r.status != "ok" for r in self._results.values())

    def badge(self) -> str:
        if not self.is_critical_ok():
            return "❌"
        if self.has_warnings():
            return "⚠️"
        return ""   # no badge = all good (clean UI)

    def warnings(self) -> list[str]:
        msgs = []
        for s, r in self._results.items():
            if r.status == "failed":
                msgs.append(f"{s} failed" + (f": {r.error}" if r.error else ""))
            elif r.status == "missing":
                msgs.append(f"{s} unavailable" + (f" ({r.note})" if r.note else ""))
            elif r.status == "stale":
                msgs.append(f"{s} cached" + (f" ({r.note})" if r.note else ""))
        return msgs

    def confidence_penalty(self) -> float:
        """
        Small confidence deduction when optional sources are missing.
        Applied by tipster.py before emitting a pick.
        """
        penalty = 0.0
        if self._results.get("team_form", SourceResult("", "ok")).status != "ok":
            penalty += 0.03   # -3% if no form data
        if self._results.get("league_stats", SourceResult("", "ok")).status != "ok":
            penalty += 0.01
        return penalty


def format_flags_for_ui(data_flags: dict) -> dict:
    """
    Convert stored flags dict to UI-ready dict.
    Returns: {badge, warnings, has_warnings, is_critical_ok}
    Used by templates to render source health badges on tip cards.
    """
    if not data_flags:
        return {"badge": "", "warnings": [], "has_warnings": False, "is_critical_ok": True}

    warnings = []
    critical_ok = True

    for source, status in data_flags.items():
        if status == "failed":
            warnings.append(f"{source} failed")
            if source in _CRITICAL:
                critical_ok = False
        elif status == "missing":
            warnings.append(f"{source} unavailable")
            if source in _CRITICAL:
                critical_ok = False
        elif status == "stale":
            warnings.append(f"{source} (cached)")

    badge = "" if not warnings else ("❌" if not critical_ok else "⚠️")
    return {
        "badge":         badge,
        "warnings":      warnings,
        "has_warnings":  bool(warnings),
        "is_critical_ok": critical_ok,
    }
