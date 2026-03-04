import os
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


def _build_embed(doc: dict) -> dict:
    """Build a Discord embed card from a fellowship document."""

    name         = doc.get("name", "Unknown Opportunity")
    organization = doc.get("organization", "Unknown Org")
    deadline     = doc.get("deadline", "Check Website")
    stipend      = doc.get("stipend", "Not Specified")
    eligibility  = doc.get("eligibility", "Not Specified")
    mode         = doc.get("mode", "Not Specified")
    apply_link   = doc.get("apply_link", "")
    tags         = doc.get("tags", [])
    trust_score  = doc.get("trust_score", 0)

    # Color based on trust score
    if trust_score >= 90:
        color = 0x00C853   # green  — highly trusted source
    elif trust_score >= 60:
        color = 0xFFAB00   # amber  — medium trust
    else:
        color = 0x546E7A   # grey   — low trust

    # Deadline urgency emoji
    deadline_display = deadline
    try:
        dl = datetime.strptime(deadline, "%Y-%m-%d")
        days_left = (dl.date() - datetime.now(timezone.utc).date()).days
        if days_left < 0:
            deadline_display = f"Closed ({deadline})"
        elif days_left <= 7:
            deadline_display = f"{deadline} ({days_left}d left!)"
        elif days_left <= 30:
            deadline_display = f"{deadline} ({days_left}d left)"
        else:
            deadline_display = f"{deadline} ({days_left}d left)"
    except ValueError:
        deadline_display = f"{deadline}"

    tags_str = "  ".join(f"`{t}`" for t in tags) if tags else "—"

    embed = {
        "title": f"{name}",
        "url": apply_link,
        "color": color,
        "fields": [
            {"name": "Organization",  "value": organization,      "inline": True},
            {"name": "Mode",          "value": mode,              "inline": True},
            {"name": "Deadline",      "value": deadline_display,  "inline": False},
            {"name": "Stipend",       "value": stipend,           "inline": True},
            {"name": "Eligibility",   "value": eligibility,       "inline": False},
            {"name": "Tags",          "value": tags_str,          "inline": False},
        ],
        "footer": {
            "text": f"Fellowship Tracker  •  Trust Score: {trust_score}/100"
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if apply_link:
        embed["fields"].append({
            "name": "Apply",
            "value": f"[Click here to apply]({apply_link})",
            "inline": False,
        })

    return embed


async def send_discord_notification(doc: dict) -> bool:
    """
    Send a Discord embed notification for a newly discovered opportunity.

    Args:
        doc: The fellowship document dict saved to MongoDB.

    Returns:
        True if sent successfully, False otherwise.
    """
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL not set in .env — skipping notification.")
        return False

    embed   = _build_embed(doc)
    payload = {
        "username":   "Fellowship Tracker",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2436/2436874.png",
        "embeds":     [embed],
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=10,
            )
            if resp.status_code in (200, 204):
                print(f"Discord notified: {doc.get('name')}")
                return True
            else:
                print(f"Discord error {resp.status_code}: {resp.text[:200]}")
                return False

    except Exception as e:
        print(f"Discord notification failed: {e}")
        return False