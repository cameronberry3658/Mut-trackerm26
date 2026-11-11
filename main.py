#!/usr/bin/env python3
"""
MUT Tracker - Main Runner
Your personal Madden Ultimate Team market intelligence tool.

Usage:
    python main.py scrape [--pages N] [--min-ovr N]    Scrape player data from MUT.gg
    python main.py watch <mutgg_id> [--buy N] [--sell N]  Add card to watchlist
    python main.py watchlist                              View your watchlist
    python main.py snipes                                 Find snipe opportunities
    python main.py report                                 Full market report
    python main.py movers                                 Price movers (24h)
    python main.py search <name>                          Search players by name
    python main.py training                               Quicksell vs Auction analysis
    python main.py demo                                   Load demo data for testing
"""

import sys
import argparse
import database as db
import scraper
import analysis
from datetime import datetime, timedelta
import random
import logging

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def cmd_scrape(args):
    """Scrape player data from MUT.gg."""
    db.init_db()
    pages = args.pages or 3
    min_ovr = args.min_ovr or None

    all_players = []
    for page in range(1, pages + 1):
        try:
            players = scraper.scrape_player_list(page=page, min_ovr=min_ovr)
            for p in players:
                db.upsert_player(p)
            all_players.extend(players)
            print(f"  Page {page}: scraped {len(players)} players")
        except Exception as e:
            print(f"  Page {page}: ERROR - {e}")
            continue

    print(f"\nTotal: {len(all_players)} players saved to database.")

    # Optionally scrape details for top players
    if args.details:
        print("\nScraping detailed stats for top players...")
        for p in all_players[:10]:
            try:
                detail = scraper.scrape_player_detail(p["url"])
                update = {**p, **detail}
                update.pop("stats", None)
                db.upsert_player(update)
                print(f"  {p['ovr']} {p['name']} - details saved")
            except Exception as e:
                print(f"  {p['name']}: ERROR - {e}")


def cmd_watch(args):
    """Add a card to the watchlist."""
    db.init_db()
    db.add_to_watchlist(
        mutgg_id=args.mutgg_id,
        target_buy=args.buy,
        target_sell=args.sell,
        notes=args.notes or ""
    )
    print(f"Added {args.mutgg_id} to watchlist")
    if args.buy:
        print(f"  Buy alert at: {args.buy:,} coins")
    if args.sell:
        print(f"  Sell alert at: {args.sell:,} coins")


def cmd_watchlist(args):
    """Display the watchlist."""
    db.init_db()
    items = db.get_watchlist()

    if not items:
        print("Watchlist is empty. Add cards with: python main.py watch <mutgg_id> --buy <price>")
        return

    print(f"\n{'='*70}")
    print(f"  YOUR WATCHLIST ({len(items)} cards)")
    print(f"{'='*70}")
    print(f"  {'OVR':>3}  {'Name':<22} {'Pos':<5} {'Current':>10} {'Buy@':>10} {'Sell@':>10}")
    print(f"  {'-'*3}  {'-'*22} {'-'*5} {'-'*10} {'-'*10} {'-'*10}")

    for item in items:
        current = f"{item['latest_price']:,}" if item.get('latest_price') else "N/A"
        buy_at = f"{item['target_buy_price']:,}" if item.get('target_buy_price') else "-"
        sell_at = f"{item['target_sell_price']:,}" if item.get('target_sell_price') else "-"
        print(f"  {item['ovr']:>3}  {item['name']:<22} {item.get('position',''):.<5} "
              f"{current:>10} {buy_at:>10} {sell_at:>10}")

    # Check alerts
    alerts = analysis.check_watchlist_alerts()
    if alerts:
        print(f"\n  !!! ACTIVE ALERTS !!!")
        for a in alerts:
            print(f"  >>> {a['message']}")


def cmd_snipes(args):
    """Find snipe opportunities."""
    db.init_db()
    threshold = args.threshold or 15.0
    snipes = analysis.detect_snipes(threshold_pct=threshold)

    if not snipes:
        print("No snipe opportunities found at current threshold.")
        print(f"  (Looking for cards {threshold}%+ below 7-day average)")
        return

    print(f"\n{'='*80}")
    print(f"  SNIPE OPPORTUNITIES (>{threshold}% below 7-day avg)")
    print(f"{'='*80}")
    print(f"  {'OVR':>3}  {'Name':<22} {'Now':>10} {'Avg':>10} {'Profit':>10} {'Disc%':>6} {'ROI%':>6}")
    print(f"  {'-'*3}  {'-'*22} {'-'*10} {'-'*10} {'-'*10} {'-'*6} {'-'*6}")

    for s in snipes[:20]:
        print(f"  {s['ovr']:>3}  {s['name']:<22} {s['current_price']:>10,} "
              f"{s['avg_price']:>10,} {s['est_profit']:>10,} "
              f"{s['discount_pct']:>5.0f}% {s['roi_pct']:>5.1f}%")


def cmd_report(args):
    """Generate full market report."""
    db.init_db()
    print(analysis.generate_report())


def cmd_movers(args):
    """Show biggest price movers."""
    db.init_db()
    hours = args.hours or 24
    movers = db.get_price_movers(hours=hours, limit=20)

    if not movers:
        print(f"No price movement data in the last {hours} hours.")
        return

    print(f"\n{'='*70}")
    print(f"  PRICE MOVERS (Last {hours}h)")
    print(f"{'='*70}")

    gainers = [m for m in movers if m["price_change"] > 0]
    decliners = [m for m in movers if m["price_change"] < 0]

    if gainers:
        print(f"\n  GAINERS:")
        for g in gainers[:10]:
            print(f"    {g['ovr']:>3} {g['name']:<22} "
                  f"{g['old_price']:>10,} -> {g['new_price']:>10,}  "
                  f"({g['pct_change']:+.1f}%)")

    if decliners:
        print(f"\n  DECLINERS:")
        for d in decliners[:10]:
            print(f"    {d['ovr']:>3} {d['name']:<22} "
                  f"{d['old_price']:>10,} -> {d['new_price']:>10,}  "
                  f"({d['pct_change']:+.1f}%)")


def cmd_search(args):
    """Search for players by name."""
    db.init_db()
    players = db.get_all_players({"name": args.name})

    if not players:
        print(f"No players found matching '{args.name}'")
        return

    print(f"\nFound {len(players)} player(s):")
    for p in players[:20]:
        print(f"  {p['ovr']:>3} OVR  {p['name']:<25} {p.get('position',''):.<6} "
              f"{p.get('program',''):<20} ID: {p['mutgg_id']}")


def cmd_training(args):
    """Show quicksell vs auction analysis."""
    db.init_db()
    plays = analysis.find_training_value_plays()

    if not plays:
        print("No data available for training analysis. Scrape some player data first.")
        return

    print(f"\n{'='*80}")
    print(f"  QUICKSELL vs AUCTION ANALYSIS")
    print(f"{'='*80}")
    print(f"  {'OVR':>3}  {'Name':<22} {'Market':>10} {'After Tax':>10} {'QS Value':>10} {'Action':<10}")
    print(f"  {'-'*3}  {'-'*22} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    for p in plays[:20]:
        print(f"  {p['ovr']:>3}  {p['name']:<22} {p.get('market_price',0):>10,} "
              f"{p['auction_after_tax']:>10,} {p['quicksell_value']:>10,} "
              f"{p['recommendation']:<10}")


def cmd_price(args):
    """Manually log a price for a card, or auto-scrape it from MUT.gg."""
    db.init_db()

    mutgg_id = args.mutgg_id

    conn = db.get_connection()
    player = conn.execute("SELECT * FROM players WHERE mutgg_id = ?", (mutgg_id,)).fetchone()
    conn.close()

    if not player:
        print(f"Player {mutgg_id} not found in database. Run 'scrape' first or check the ID.")
        return

    if args.auto:
        print(f"Attempting to scrape price for {player['name']} from MUT.gg...")
        try:
            from price_scraper import scrape_player_price
            price_data = scrape_player_price(player["url"])
            if price_data and price_data.get("price"):
                db.add_price_snapshot(mutgg_id, price_data["price"], price_data.get("lowest_bin"))
                print(f"  {player['ovr']} {player['name']}: {price_data['price']:,} coins")
                print(f"  Saved to database.")
            else:
                print(f"  Could not scrape price. Try manual entry:")
                print(f"  python main.py price {mutgg_id} <price>")
        except ImportError:
            print("  price_scraper.py not found or Selenium not installed.")
            print("  Install with: pip install selenium")
            print(f"  Or enter price manually: python main.py price {mutgg_id} <price>")
        return

    if not args.coin_price:
        history = db.get_price_history(mutgg_id, limit=10)
        print(f"\n  {player['ovr']} OVR {player['name']} ({player['position']}) - {player['program']}")
        if history:
            print(f"  {'Date':<20} {'Price':>12} {'Lowest BIN':>12}")
            print(f"  {'-'*20} {'-'*12} {'-'*12}")
            for h in history:
                ts = h['timestamp'][:16].replace('T', ' ')
                low = f"{h['lowest_bin']:,}" if h.get('lowest_bin') else "N/A"
                print(f"  {ts:<20} {h['price']:>12,} {low:>12}")
        else:
            print(f"  No price history yet. Log one:")
            print(f"  python main.py price {mutgg_id} <price>")
        return

    price = args.coin_price
    db.add_price_snapshot(mutgg_id, price)
    print(f"  Logged: {player['ovr']} {player['name']} = {price:,} coins")

    import analysis as an
    alerts = an.check_watchlist_alerts()
    for a in alerts:
        if a["mutgg_id"] == mutgg_id:
            print(f"\n  >>> {a['message']}")


def cmd_prices(args):
    """Bulk scrape prices for all players or watchlist using Selenium."""
    db.init_db()

    try:
        from price_scraper import scrape_prices_bulk
    except ImportError:
        print("price_scraper.py not found or Selenium not installed.")
        print("Install with: pip install selenium")
        print("\nAlternatively, log prices manually:")
        print("  python main.py price <mutgg_id> <price>")
        return

    if args.watchlist_only:
        items = db.get_watchlist()
        if not items:
            print("Watchlist is empty.")
            return
        player_ids = [item["mutgg_id"] for item in items]
        print(f"Scraping prices for {len(player_ids)} watchlist cards...")
    else:
        conn = db.get_connection()
        rows = conn.execute("SELECT mutgg_id, url FROM players WHERE url IS NOT NULL AND url != '#' ORDER BY ovr DESC LIMIT ?",
                           (args.limit,)).fetchall()
        conn.close()
        player_ids = [r["mutgg_id"] for r in rows]
        print(f"Scraping prices for top {len(player_ids)} players...")

    results = scrape_prices_bulk(player_ids)
    success = sum(1 for r in results if r.get("price"))
    print(f"\nDone: {success}/{len(results)} prices scraped successfully.")

    import analysis as an
    alerts = an.check_watchlist_alerts()
    if alerts:
        print(f"\n  !!! ALERTS TRIGGERED !!!")
        for a in alerts:
            print(f"  >>> {a['message']}")


def cmd_demo(args):
    """Load demo data so you can test the analysis features."""
    db.init_db()
    print("Loading demo data...")

    # Sample MUT players
    demo_players = [
        {"mutgg_id": "26-76017838", "player_id": "17838", "name": "Tyreek Hill", "ovr": 99,
         "position": "WR", "archetype": "Deep Threat", "program": "Sugar Rush",
         "team": "Miami Dolphins", "speed": 99, "quicksell_value": 350000,
         "url": "https://www.mut.gg/players/17838-tyreek-hill/26-76017838/", "date_added": "04/05/2026"},
        {"mutgg_id": "26-76023024", "player_id": "23024", "name": "Brian Branch", "ovr": 99,
         "position": "SS", "archetype": "Run Support", "program": "Sugar Rush",
         "team": "Detroit Lions", "speed": 98, "quicksell_value": 350000,
         "url": "#", "date_added": "04/05/2026"},
        {"mutgg_id": "26-76000001", "player_id": "32636", "name": "Josh Allen", "ovr": 99,
         "position": "QB", "archetype": "Improviser", "program": "Sugar Rush",
         "team": "Buffalo Bills", "speed": 97, "quicksell_value": 350000,
         "url": "#", "date_added": "04/05/2026"},
        {"mutgg_id": "26-115014678", "player_id": "14678", "name": "Brock Bowers", "ovr": 99,
         "position": "TE", "archetype": "Vertical Threat", "program": "Flashbacks",
         "team": "Las Vegas Raiders", "speed": 97, "quicksell_value": 250000,
         "url": "#", "date_added": "04/01/2026"},
        {"mutgg_id": "26-114000692", "player_id": "692", "name": "Cornelius Bennett", "ovr": 99,
         "position": "SAM", "archetype": "Run Stopper", "program": "Ultimate Legends",
         "team": "Buffalo Bills", "speed": 96, "quicksell_value": 500000,
         "url": "#", "date_added": "04/10/2026"},
        {"mutgg_id": "26-114000264", "player_id": "264", "name": "Corey Dillon", "ovr": 99,
         "position": "HB", "archetype": "Power Back", "program": "Ultimate Legends",
         "team": "Cincinnati Bengals", "speed": 98, "quicksell_value": 500000,
         "url": "#", "date_added": "04/10/2026"},
        {"mutgg_id": "26-12201426", "player_id": "1426", "name": "Darius Slay Jr", "ovr": 99,
         "position": "CB", "archetype": "Zone", "program": "Tribute",
         "team": "Philadelphia Eagles", "speed": 98, "quicksell_value": 250000,
         "url": "#", "date_added": "04/08/2026"},
        {"mutgg_id": "26-20017838B", "player_id": "17838B", "name": "Tyreek Hill MF", "ovr": 90,
         "position": "WR", "archetype": "Shadow Innovator", "program": "Most Feared",
         "team": "Miami Dolphins", "speed": 95, "quicksell_value": 38000,
         "url": "#", "date_added": "10/15/2025"},
        {"mutgg_id": "26-CORE001", "player_id": "C001", "name": "Lamar Jackson", "ovr": 92,
         "position": "QB", "archetype": "Scrambler", "program": "Core",
         "team": "Baltimore Ravens", "speed": 96, "quicksell_value": 45000,
         "url": "#", "date_added": "08/15/2025"},
        {"mutgg_id": "26-TOTW001", "player_id": "TW001", "name": "CeeDee Lamb", "ovr": 95,
         "position": "WR", "archetype": "Route Runner", "program": "TOTW",
         "team": "Dallas Cowboys", "speed": 96, "quicksell_value": 85000,
         "url": "#", "date_added": "01/20/2026"},
    ]

    for p in demo_players:
        db.upsert_player(p)

    # Generate fake price history (7 days of data, multiple snapshots per day)
    import random
    base_prices = {
        "26-76017838": 680000,    # Tyreek Sugar Rush
        "26-76023024": 520000,    # Brian Branch
        "26-76000001": 750000,    # Josh Allen
        "26-115014678": 410000,   # Brock Bowers
        "26-114000692": 890000,   # Cornelius Bennett
        "26-114000264": 720000,   # Corey Dillon
        "26-12201426": 380000,    # Darius Slay
        "26-20017838B": 45000,    # Tyreek MF (old card)
        "26-CORE001": 62000,      # Lamar Core
        "26-TOTW001": 185000,     # CeeDee TOTW
    }

    conn = db.get_connection()
    now = datetime.now()

    for mutgg_id, base in base_prices.items():
        for day in range(7, -1, -1):
            for hour_offset in [0, 6, 12, 18]:
                ts = now - timedelta(days=day, hours=hour_offset)
                # Add some realistic price movement
                volatility = random.uniform(-0.12, 0.12)
                # Trend: newer cards trending up, older cards trending down
                trend = (7 - day) * 0.005 if "76" in mutgg_id else -(7 - day) * 0.008
                price = int(base * (1 + volatility + trend))
                price = max(price, 1000)  # floor

                conn.execute("""
                    INSERT INTO price_history (mutgg_id, platform, price, lowest_bin, timestamp)
                    VALUES (?, 'ps', ?, ?, ?)
                """, (mutgg_id, price, int(price * 0.95), ts.isoformat()))

    # Make Tyreek's latest price a snipe opportunity (way below average)
    conn.execute("""
        INSERT INTO price_history (mutgg_id, platform, price, lowest_bin, timestamp)
        VALUES ('26-76017838', 'ps', 480000, 475000, ?)
    """, (now.isoformat(),))

    # Make CeeDee also a snipe
    conn.execute("""
        INSERT INTO price_history (mutgg_id, platform, price, lowest_bin, timestamp)
        VALUES ('26-TOTW001', 'ps', 135000, 130000, ?)
    """, (now.isoformat(),))

    conn.commit()
    conn.close()

    # Add some watchlist items
    db.add_to_watchlist("26-76017838", target_buy=500000, target_sell=900000,
                        notes="Main WR - want to buy on dip")
    db.add_to_watchlist("26-76000001", target_buy=600000, target_sell=1000000,
                        notes="Need for theme team")
    db.add_to_watchlist("26-114000264", target_buy=650000, notes="Backup HB option")

    print(f"  Loaded {len(demo_players)} players with 7 days of price history")
    print(f"  Added 3 watchlist items")
    print(f"  Planted 2 snipe opportunities (Tyreek Hill, CeeDee Lamb)")
    print(f"\nTry these commands:")
    print(f"  python main.py report       - Full market report")
    print(f"  python main.py snipes       - Find the planted snipes")
    print(f"  python main.py watchlist    - Check your watchlist")
    print(f"  python main.py movers       - See price movers")
    print(f"  python main.py search hill  - Search for Tyreek")
    print(f"  python main.py training     - Quicksell vs Auction")


def main():
    parser = argparse.ArgumentParser(
        description="MUT Tracker - Personal Madden Ultimate Team Market Intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command")

    # scrape
    sp = subparsers.add_parser("scrape", help="Scrape player data from MUT.gg")
    sp.add_argument("--pages", type=int, default=3, help="Number of pages to scrape (default: 3)")
    sp.add_argument("--min-ovr", type=int, help="Minimum OVR to scrape")
    sp.add_argument("--details", action="store_true", help="Also scrape detailed stats")

    # watch
    sp = subparsers.add_parser("watch", help="Add card to watchlist")
    sp.add_argument("mutgg_id", help="MUT.gg card ID (e.g. 26-76017838)")
    sp.add_argument("--buy", type=int, help="Alert when price drops to this")
    sp.add_argument("--sell", type=int, help="Alert when price rises to this")
    sp.add_argument("--notes", help="Notes about this card")

    # watchlist
    subparsers.add_parser("watchlist", help="View your watchlist")

    # snipes
    sp = subparsers.add_parser("snipes", help="Find snipe opportunities")
    sp.add_argument("--threshold", type=float, default=15.0,
                    help="Min %% below average to flag (default: 15)")

    # report
    subparsers.add_parser("report", help="Generate full market report")

    # movers
    sp = subparsers.add_parser("movers", help="Show price movers")
    sp.add_argument("--hours", type=int, default=24, help="Lookback period in hours")

    # search
    sp = subparsers.add_parser("search", help="Search players by name")
    sp.add_argument("name", help="Player name to search")

    # training
    subparsers.add_parser("training", help="Quicksell vs Auction analysis")

    # price (manual or single auto)
    sp = subparsers.add_parser("price", help="Log or view price for a card")
    sp.add_argument("mutgg_id", help="MUT.gg card ID (e.g. 26-115020571)")
    sp.add_argument("coin_price", type=int, nargs="?", help="Price in coins (omit to view history)")
    sp.add_argument("--auto", action="store_true", help="Auto-scrape price from MUT.gg (needs Selenium)")

    # prices (bulk auto)
    sp = subparsers.add_parser("prices", help="Bulk scrape prices (needs Selenium)")
    sp.add_argument("--watchlist-only", action="store_true", help="Only scrape watchlist cards")
    sp.add_argument("--limit", type=int, default=50, help="Max players to scrape (default: 50)")

    # demo
    subparsers.add_parser("demo", help="Load demo data for testing")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "scrape": cmd_scrape,
        "watch": cmd_watch,
        "watchlist": cmd_watchlist,
        "snipes": cmd_snipes,
        "report": cmd_report,
        "movers": cmd_movers,
        "search": cmd_search,
        "training": cmd_training,
        "price": cmd_price,
        "prices": cmd_prices,
        "demo": cmd_demo,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
