"""
MUT Tracker - Analysis Engine
Detects snipe opportunities, calculates set profitability,
monitors watchlist alerts, and identifies market trends.
"""

import database as db
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# EA auction house tax rate
EA_TAX_RATE = 0.10


def calculate_profit(buy_price: int, sell_price: int) -> int:
    """Calculate profit after EA's 10% auction house tax."""
    tax = int(sell_price * EA_TAX_RATE)
    return sell_price - buy_price - tax


def detect_snipes(threshold_pct: float = 15.0) -> list:
    """
    Find cards currently listed well below their market average.
    
    A "snipe" is when someone lists a card significantly below its going rate.
    We flag anything where current price is >= threshold_pct below the 7-day avg.
    
    Returns list of snipe opportunities sorted by profit potential.
    """
    undervalued = db.get_undervalued_cards(threshold_pct)

    snipes = []
    for card in undervalued:
        est_profit = calculate_profit(card["current_price"], card["avg_price"])
        if est_profit > 0:
            snipes.append({
                **card,
                "est_profit": est_profit,
                "roi_pct": round((est_profit / card["current_price"]) * 100, 1),
            })

    # Sort by estimated profit descending
    snipes.sort(key=lambda x: x["est_profit"], reverse=True)
    return snipes


def check_watchlist_alerts() -> list:
    """
    Check watchlist items against their target prices.
    Returns list of triggered alerts.
    """
    watchlist = db.get_watchlist()
    alerts = []

    for item in watchlist:
        current = item.get("latest_price")
        if current is None:
            continue

        # Buy alert: price dropped to or below target
        if item.get("target_buy_price") and current <= item["target_buy_price"]:
            alerts.append({
                "type": "BUY",
                "name": item["name"],
                "ovr": item["ovr"],
                "position": item["position"],
                "current_price": current,
                "target_price": item["target_buy_price"],
                "mutgg_id": item["mutgg_id"],
                "message": f"BUY ALERT: {item['ovr']} {item['name']} dropped to {current:,} "
                           f"(target: {item['target_buy_price']:,})"
            })

        # Sell alert: price rose to or above target
        if item.get("target_sell_price") and current >= item["target_sell_price"]:
            alerts.append({
                "type": "SELL",
                "name": item["name"],
                "ovr": item["ovr"],
                "position": item["position"],
                "current_price": current,
                "target_price": item["target_sell_price"],
                "mutgg_id": item["mutgg_id"],
                "message": f"SELL ALERT: {item['ovr']} {item['name']} rose to {current:,} "
                           f"(target: {item['target_sell_price']:,})"
            })

    return alerts


def calculate_set_profitability(set_name: str, input_cards: list, output_value: int) -> dict:
    """
    Calculate whether completing a set is profitable.
    
    Args:
        set_name: Name of the set
        input_cards: List of dicts with {'mutgg_id': str, 'quantity': int}
        output_value: Coin value of the set reward (sell price or quicksell)
    
    Returns dict with cost breakdown and profit.
    """
    total_input_cost = 0
    card_costs = []

    conn = db.get_connection()
    for card in input_cards:
        # Get latest price for this card
        row = conn.execute("""
            SELECT ph.price, p.name, p.ovr
            FROM price_history ph
            JOIN players p ON p.mutgg_id = ph.mutgg_id
            WHERE ph.mutgg_id = ?
            ORDER BY ph.timestamp DESC LIMIT 1
        """, (card["mutgg_id"],)).fetchone()

        if row:
            cost = row["price"] * card.get("quantity", 1)
            total_input_cost += cost
            card_costs.append({
                "name": row["name"],
                "ovr": row["ovr"],
                "unit_price": row["price"],
                "quantity": card.get("quantity", 1),
                "total": cost,
            })
    conn.close()

    # Output after tax
    output_after_tax = int(output_value * (1 - EA_TAX_RATE))
    profit = output_after_tax - total_input_cost

    result = {
        "set_name": set_name,
        "input_cards": card_costs,
        "total_input_cost": total_input_cost,
        "output_value": output_value,
        "output_after_tax": output_after_tax,
        "profit": profit,
        "profitable": profit > 0,
        "roi_pct": round((profit / total_input_cost) * 100, 1) if total_input_cost > 0 else 0,
    }

    # Save to DB
    conn = db.get_connection()
    conn.execute("""
        INSERT INTO sets (set_name, input_cost, output_value, profit)
        VALUES (?, ?, ?, ?)
    """, (set_name, total_input_cost, output_value, profit))
    conn.commit()
    conn.close()

    return result


def get_market_summary() -> dict:
    """
    Generate an overall market health summary.
    Shows trending up/down cards, volume indicators, etc.
    """
    conn = db.get_connection()

    # Total players tracked
    total_players = conn.execute("SELECT COUNT(*) as c FROM players").fetchone()["c"]

    # Total price data points
    total_prices = conn.execute("SELECT COUNT(*) as c FROM price_history").fetchone()["c"]

    # Price data in last 24h
    recent_prices = conn.execute("""
        SELECT COUNT(*) as c FROM price_history
        WHERE timestamp >= datetime('now', '-24 hours')
    """).fetchone()["c"]

    # Watchlist count
    watchlist_count = conn.execute("SELECT COUNT(*) as c FROM watchlist").fetchone()["c"]

    # Snipes detected today
    snipes_today = conn.execute("""
        SELECT COUNT(*) as c FROM snipe_log
        WHERE detected_at >= datetime('now', '-24 hours')
    """).fetchone()["c"]

    conn.close()

    # Get movers
    top_gainers = db.get_price_movers(hours=24, limit=5)
    gainers = [m for m in top_gainers if m["price_change"] > 0]
    decliners = [m for m in top_gainers if m["price_change"] < 0]

    return {
        "total_players": total_players,
        "total_price_snapshots": total_prices,
        "snapshots_last_24h": recent_prices,
        "watchlist_items": watchlist_count,
        "snipes_today": snipes_today,
        "top_gainers": gainers[:5],
        "top_decliners": sorted(decliners, key=lambda x: x["price_change"])[:5],
    }


def find_training_value_plays(training_coin_ratio: float = None) -> list:
    """
    Find cards where quickselling for training is more valuable
    than selling on the auction house (or vice versa).
    
    If training_coin_ratio is provided (e.g., 10 means 1 training = 10 coins),
    it calculates whether to quicksell or auction each card.
    """
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT p.mutgg_id, p.name, p.ovr, p.position, p.quicksell_value,
               (SELECT ph.price FROM price_history ph
                WHERE ph.mutgg_id = p.mutgg_id
                ORDER BY ph.timestamp DESC LIMIT 1) as market_price
        FROM players p
        WHERE p.quicksell_value > 0
        ORDER BY p.ovr DESC
    """).fetchall()
    conn.close()

    plays = []
    for row in rows:
        row = dict(row)
        market = row.get("market_price", 0) or 0
        qs = row["quicksell_value"]
        auction_after_tax = int(market * (1 - EA_TAX_RATE))

        if market > 0:
            row["auction_after_tax"] = auction_after_tax
            row["recommendation"] = "AUCTION" if auction_after_tax > qs else "QUICKSELL"
            row["difference"] = abs(auction_after_tax - qs)
            plays.append(row)

    plays.sort(key=lambda x: x["difference"], reverse=True)
    return plays


def generate_report() -> str:
    """Generate a text-based market report."""
    summary = get_market_summary()
    snipes = detect_snipes(threshold_pct=15.0)
    alerts = check_watchlist_alerts()

    lines = []
    lines.append("=" * 60)
    lines.append(f"  MUT TRACKER - MARKET REPORT")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)

    lines.append(f"\n--- DATABASE STATS ---")
    lines.append(f"  Players tracked:     {summary['total_players']:,}")
    lines.append(f"  Price snapshots:     {summary['total_price_snapshots']:,}")
    lines.append(f"  Last 24h snapshots:  {summary['snapshots_last_24h']:,}")
    lines.append(f"  Watchlist items:     {summary['watchlist_items']}")
    lines.append(f"  Snipes today:        {summary['snipes_today']}")

    if summary["top_gainers"]:
        lines.append(f"\n--- TOP GAINERS (24h) ---")
        for g in summary["top_gainers"]:
            lines.append(f"  {g['ovr']} {g['name']:20s}  +{g['price_change']:>8,} coins ({g['pct_change']:+.1f}%)")

    if summary["top_decliners"]:
        lines.append(f"\n--- TOP DECLINERS (24h) ---")
        for d in summary["top_decliners"]:
            lines.append(f"  {d['ovr']} {d['name']:20s}  {d['price_change']:>8,} coins ({d['pct_change']:+.1f}%)")

    if snipes:
        lines.append(f"\n--- SNIPE OPPORTUNITIES ---")
        for s in snipes[:10]:
            lines.append(f"  {s['ovr']} {s['name']:20s}  Now: {s['current_price']:>8,}  "
                         f"Avg: {s['avg_price']:>8,}  Est Profit: {s['est_profit']:>8,}  "
                         f"({s['discount_pct']:.0f}% below avg)")

    if alerts:
        lines.append(f"\n--- WATCHLIST ALERTS ---")
        for a in alerts:
            lines.append(f"  [{a['type']}] {a['message']}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


if __name__ == "__main__":
    print(generate_report())
