"""
Earnings notification service — Slack webhook and/or SMTP email.

Called after a post-brief is saved (onboarding or synthesis).
Only notifies watchlist subscribers whose alert_conditions are met.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def _conditions_met(alert_conditions: Dict[str, Any], beat_miss: Optional[str], guidance_tone: Optional[str]) -> bool:
    """Return True if this result should trigger a notification given the user's conditions."""
    if not alert_conditions:
        return True  # default: always notify

    notify_on = alert_conditions.get("notify_on")  # list: ["miss"], ["beat","miss"], etc.
    if notify_on and beat_miss and beat_miss not in notify_on:
        return False

    if alert_conditions.get("guidance_cut_only") and guidance_tone != "lowered":
        return False

    return True


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def _beat_miss_emoji(beat_miss: Optional[str]) -> str:
    return {"beat": "✅", "miss": "❌", "in_line": "➖"}.get(beat_miss or "", "❔")


def _guidance_label(tone: Optional[str]) -> str:
    return {"raised": "↑ Raised", "lowered": "↓ Lowered", "maintained": "→ Maintained", "withdrawn": "⚠️ Withdrawn"}.get(tone or "", "—")


async def _send_slack(
    company_name: str,
    ticker: str,
    period: str,
    beat_miss: Optional[str],
    guidance_tone: Optional[str],
    revenue: Optional[float],
    highlights: List[str],
    summary: Optional[str],
) -> None:
    if not SLACK_WEBHOOK_URL:
        return

    emoji = _beat_miss_emoji(beat_miss)
    rev_str = f"€{revenue:,.0f}m" if revenue else "—"
    url = f"{APP_URL}/earnings/{ticker}/{period}"

    highlight_lines = "\n".join(f"• {h}" for h in highlights[:3]) if highlights else "—"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {company_name} ({ticker}) — {period}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Result:*\n{(beat_miss or '—').replace('_', ' ').title()}"},
                {"type": "mrkdwn", "text": f"*Revenue:*\n{rev_str}"},
                {"type": "mrkdwn", "text": f"*Guidance:*\n{_guidance_label(guidance_tone)}"},
            ],
        },
    ]

    if highlight_lines != "—":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Key Highlights:*\n{highlight_lines}"},
        })

    if summary:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Assessment:*\n{summary[:300]}"},
        })

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Open Analysis →"},
                "url": url,
                "style": "primary",
            }
        ],
    })

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(SLACK_WEBHOOK_URL, json={"blocks": blocks})
    except Exception:
        pass  # Non-critical — never let notification failure break the main flow


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _send_email_digest(
    to_emails: List[str],
    company_name: str,
    ticker: str,
    period: str,
    beat_miss: Optional[str],
    guidance_tone: Optional[str],
    revenue: Optional[float],
    highlights: List[str],
    summary: Optional[str],
) -> None:
    if not to_emails:
        return
    try:
        from services.email import _send_email
    except Exception:
        return

    emoji = _beat_miss_emoji(beat_miss)
    rev_str = f"€{revenue:,.0f}m" if revenue else "—"
    url = f"{APP_URL}/earnings/{ticker}/{period}"
    hl_text = "\n".join(f"  • {h}" for h in highlights[:3]) if highlights else "  —"
    guidance_str = _guidance_label(guidance_tone)

    body = (
        f"{emoji} {company_name} ({ticker}) — {period}\n\n"
        f"Result: {(beat_miss or '—').replace('_', ' ').title()}\n"
        f"Revenue: {rev_str}\n"
        f"Guidance: {guidance_str}\n\n"
        f"Key Highlights:\n{hl_text}\n"
    )
    if summary:
        body += f"\nAssessment:\n{summary[:400]}\n"
    body += f"\nOpen analysis: {url}\n"

    try:
        _send_email(
            to_emails=to_emails,
            subject=f"[EarningIntel] {emoji} {ticker} {period} — {(beat_miss or 'Results').replace('_', ' ').title()}",
            body=body,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def notify_earnings_result(
    db_session,  # AsyncSession — typed loosely to avoid circular import
    company_name: str,
    ticker: str,
    period: str,
    beat_miss: Optional[str],
    guidance_tone: Optional[str],
    revenue: Optional[float],
    highlights: List[str],
    summary: Optional[str],
) -> None:
    """
    Send Slack + email notifications for a completed earnings result.
    Respects per-user alert_conditions on their watchlist entry.
    """
    from sqlalchemy import text

    # 1. Always try Slack (channel-level, not per-user)
    await _send_slack(company_name, ticker, period, beat_miss, guidance_tone, revenue, highlights, summary)

    # 2. Email watchlist subscribers who want post-brief notifications
    try:
        result = await db_session.execute(
            text(
                """
                SELECT user_email, alert_conditions
                FROM watchlists
                WHERE ticker = :ticker AND notify_post_brief = true
                """
            ),
            {"ticker": ticker.upper()},
        )
        rows = result.mappings().all()
    except Exception:
        return

    email_targets = []
    for row in rows:
        conditions = {}
        if row["alert_conditions"]:
            try:
                conditions = row["alert_conditions"] if isinstance(row["alert_conditions"], dict) else json.loads(row["alert_conditions"])
            except Exception:
                pass
        if _conditions_met(conditions, beat_miss, guidance_tone):
            email_targets.append(row["user_email"])

    if email_targets:
        _send_email_digest(email_targets, company_name, ticker, period, beat_miss, guidance_tone, revenue, highlights, summary)
