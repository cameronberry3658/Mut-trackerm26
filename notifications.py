"""
MUT Tracker - Notifications
Send alerts via Discord webhook (or extend to SMS/email).

Setup:
1. Create a Discord server (or use your existing one)
2. Go to Server Settings > Integrations > Webhooks > New Webhook
3. Copy the webhook URL
4. Set it in config.py or as environment variable DISCORD_WEBHOOK_URL
"""

import requests
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Set your Discord webhook URL here or via environment variable
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def send_discord_alert(message: str, embed: dict = None, webhook_url: str = None):
    """
    Send a message to Discord via webhook.
    
    Args:
        message: Plain text message
        embed: Optional Discord embed object for rich formatting
        webhook_url: Override the default webhook URL
    """
    url = webhook_url or DISCORD_WEBHOOK_URL
    if not url:
        logger.warning("No Discord webhook URL configured. Set DISCORD_WEBHOOK_URL env var.")
        print(f"[ALERT] {message}")
        return False

    payload = {"content": message}
    if embed:
        payload["embeds"] = [embed]

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"Discord alert sent: {message[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to send Discord alert: {e}")
        return False


def format_snipe_embed(snipe: dict) -> dict:
    """Format a snipe opportunity as a Discord embed."""
    return {
        "title": f"SNIPE: {snipe['ovr']} OVR {snipe['name']}",
        "color": 0x00FF00,  # green
        "fields": [
            {"name": "Position", "value": snipe.get("position", "N/A"), "inline": True},
            {"name": "Program", "value": snipe.get("program", "N/A"), "inline": True},
            {"name": "Current Price", "value": f"{snipe['current_price']:,} coins", "inline": True},
            {"name": "7-Day Average", "value": f"{snipe['avg_price']:,} coins", "inline": True},
            {"name": "Est. Profit", "value": f"{snipe['est_profit']:,} coins", "inline": True},
            {"name": "Discount", "value": f"{snipe['discount_pct']:.0f}% below avg", "inline": True},
        ],
        "footer": {"text": f"MUT Tracker | {datetime.now().strftime('%I:%M %p')}"},
    }


def format_watchlist_embed(alert: dict) -> dict:
    """Format a watchlist alert as a Discord embed."""
    color = 0x00FF00 if alert["type"] == "BUY" else 0xFF6600  # green for buy, orange for sell
    return {
        "title": f"{'📉 BUY' if alert['type'] == 'BUY' else '📈 SELL'} ALERT",
        "description": alert["message"],
        "color": color,
        "fields": [
            {"name": "Card", "value": f"{alert['ovr']} OVR {alert['name']}", "inline": True},
            {"name": "Position", "value": alert.get("position", "N/A"), "inline": True},
            {"name": "Current Price", "value": f"{alert['current_price']:,}", "inline": True},
            {"name": "Target Price", "value": f"{alert['target_price']:,}", "inline": True},
        ],
        "footer": {"text": f"MUT Tracker | {datetime.now().strftime('%I:%M %p')}"},
    }


def send_snipe_alerts(snipes: list, min_profit: int = 10000):
    """Send Discord alerts for profitable snipes."""
    for snipe in snipes:
        if snipe.get("est_profit", 0) >= min_profit:
            embed = format_snipe_embed(snipe)
            send_discord_alert(
                f"🎯 Snipe detected: **{snipe['name']}** at {snipe['current_price']:,} "
                f"(avg {snipe['avg_price']:,})",
                embed=embed
            )


def send_watchlist_alerts(alerts: list):
    """Send Discord alerts for watchlist triggers."""
    for alert in alerts:
        embed = format_watchlist_embed(alert)
        send_discord_alert(alert["message"], embed=embed)


if __name__ == "__main__":
    # Test
    print("Testing Discord notification...")
    test_snipe = {
        "name": "Tyreek Hill",
        "ovr": 99,
        "position": "WR",
        "program": "Sugar Rush",
        "current_price": 480000,
        "avg_price": 680000,
        "est_profit": 132000,
        "discount_pct": 29.4,
    }
    embed = format_snipe_embed(test_snipe)
    print(json.dumps(embed, indent=2))

    if DISCORD_WEBHOOK_URL:
        send_discord_alert("🧪 MUT Tracker test alert!", embed=embed)
    else:
        print("\nNo webhook URL set. To enable Discord alerts:")
        print("  export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'")
