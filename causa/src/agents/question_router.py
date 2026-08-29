"""
question_router.py — resolves a free-form user question ("why did revenue
drop in November?") into a governed {kpi_id, period_current, period_previous}
triple that api/routes/investigations.py can feed straight into the real
create_investigation flow.

This is the ONLY module in the codebase that calls OpenAI, and it is used
for exactly one narrow, low-stakes task: picking which already-governed KPI
and month the user means. It never generates the answer itself and never
touches the causal engine -- whatever OpenAI returns is validated against
the caller-supplied kpi_ids/months allowlists before use, and any missing
key, network failure, or out-of-allowlist response falls back to a
dependency-free keyword matcher so the feature degrades gracefully rather
than failing closed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    # Mirrors llm_client._load_dotenv -- kept as its own copy so this module
    # has no import-order dependency on agents.llm_client.
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

OPENAI_MODEL = os.environ.get("OPENAI_QUESTION_ROUTER_MODEL", "gpt-4o-mini")

_MONTH_NAMES = {
    "january": "01", "february": "02", "march": "03", "april": "04", "may": "05", "june": "06",
    "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12",
}

_KPI_ALIASES: dict[str, list[str]] = {
    "revenue": ["revenue", "sales", "income", "money"],
    "orders": ["orders", "order volume", "order count", "number of orders"],
    "aov": ["aov", "average order value", "basket size", "order size"],
    "freight_revenue": ["freight", "shipping revenue", "shipping cost"],
    "avg_delivery_days": ["delivery time", "delivery days", "shipping time", "how long delivery"],
    "on_time_delivery_rate": ["on-time", "on time delivery", "late deliveries", "delayed orders"],
    "avg_review_score": ["review score", "rating", "star rating", "customer satisfaction"],
    "review_volume": ["review volume", "number of reviews", "how many reviews"],
    "repeat_purchase_rate": ["repeat purchase", "retention", "repeat customers", "returning customers"],
}


def has_openai_credentials() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def _previous_period(period_current: str) -> str:
    year, month = (int(x) for x in period_current.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def _keyword_fallback(question: str, kpi_ids: list[str], months: list[str]) -> dict:
    ql = question.lower()

    kpi_id = "revenue" if "revenue" in kpi_ids else kpi_ids[0]
    for kid, aliases in _KPI_ALIASES.items():
        if kid not in kpi_ids:
            continue
        if any(alias in ql for alias in aliases):
            kpi_id = kid
            break

    period_current: Optional[str] = None
    direct = re.search(r"(20\d{2}-\d{2})", question)
    if direct and direct.group(1) in months:
        period_current = direct.group(1)
    else:
        named = re.search(
            r"(" + "|".join(_MONTH_NAMES) + r")[a-z]*\s+(\d{4})", ql,
        )
        if named:
            candidate = f"{named.group(2)}-{_MONTH_NAMES[named.group(1)]}"
            if candidate in months:
                period_current = candidate

    if period_current is None:
        period_current = months[-1] if months else "2017-11"

    return {
        "kpi_id": kpi_id,
        "period_current": period_current,
        "period_previous": _previous_period(period_current),
        "resolver": "keyword",
    }


def resolve_question(question: str, kpi_ids: list[str], months: list[str]) -> dict:
    """Returns {kpi_id, period_current, period_previous, resolver}. `resolver`
    is "openai" or "keyword" so callers/UI can be honest about which path
    actually answered."""
    if not question or not question.strip():
        raise ValueError("question must be non-empty")
    if not kpi_ids or not months:
        raise ValueError("kpi_ids and months must be non-empty allowlists")

    if not has_openai_credentials():
        return _keyword_fallback(question, kpi_ids, months)

    try:
        import httpx

        system = (
            "You map a user's free-form analytics question to exactly one governed KPI id "
            "and one governed analysis month. Reply with ONLY compact JSON of the shape "
            '{"kpi_id": "...", "period_current": "YYYY-MM"} and nothing else -- no prose, '
            "no markdown fences.\n"
            f"Allowed kpi_id values: {', '.join(kpi_ids)}.\n"
            f"Allowed period_current values: {', '.join(months)}.\n"
            "If the question does not name a month, use the most recent allowed period. "
            "If it does not clearly name a KPI, use \"revenue\" when it is allowed, "
            "otherwise the first allowed id."
        )
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
                "temperature": 0,
                "max_tokens": 60,
                "response_format": {"type": "json_object"},
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"] or "{}"
        data = json.loads(raw)
        kpi_id = data.get("kpi_id")
        period_current = data.get("period_current")
        if kpi_id not in kpi_ids or period_current not in months:
            raise ValueError(f"OpenAI returned an ungoverned value: {data!r}")
        return {
            "kpi_id": kpi_id,
            "period_current": period_current,
            "period_previous": _previous_period(period_current),
            "resolver": "openai",
        }
    except Exception:
        # Any failure (missing/invalid key, network error, rate limit,
        # malformed/ungoverned response) -- degrade to the deterministic
        # keyword matcher rather than surfacing an error to the user.
        return _keyword_fallback(question, kpi_ids, months)
