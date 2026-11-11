#!/usr/bin/env python3
"""
MUT Tracker - Auto Runner
Run this on a schedule (cron job) to automatically:
1. Scrape latest prices from MUT.gg
2. Detect snipe opportunities
3. Check watchlist alerts
4. Send Discord notifications

Cron example (every 30 minutes):
    */30 * * * * cd /path/to/mut-tracker && python auto_run.py >> logs/auto.log 2>&1

Cron example (every hour during gaming hours 4pm-midnight):
    0 16-23 * * * cd /path/to/mut-tracker && python auto_run.py >> logs/auto.log 2>&1
"""

import database as db
import scraper
import analysis
import notifications
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def run():
    """Full auto-run cycle."""
    logger.info("=" * 50)
    logger.info("MUT Tracker Auto-Run Starting")
    logger.info("=" * 50)

    # 1. Initialize DB
    db.init_db()

    # 2. Scrape latest player data (first 5 pages = top ~75 cards)
    logger.info("Phase 1: Scraping player data...")
    total_scraped = 0
    for page in range(1, 6):
        try:
            players = scraper.scrape_player_list(page=page)
            for p in players:
                db.upsert_player(p)
            total_scraped += len(players)
        except Exception as e:
            logger.error(f"Scrape error on page {page}: {e}")
            continue

    logger.info(f"Scraped {total_scraped} players")

    # 3. Detect snipes
    logger.info("Phase 2: Detecting snipe opportunities...")
    snipes = analysis.detect_snipes(threshold_pct=15.0)
    if snipes:
        logger.info(f"Found {len(snipes)} snipe opportunities!")
        for s in snipes[:5]:
            logger.info(f"  SNIPE: {s['ovr']} {s['name']} - "
                        f"Now: {s['current_price']:,}, Avg: {s['avg_price']:,}, "
                        f"Profit: {s['est_profit']:,}")
            # Log to DB
            db.log_snipe(s["mutgg_id"], s["current_price"], s["avg_price"])

        # Send Discord alerts for big snipes
        notifications.send_snipe_alerts(snipes, min_profit=10000)
    else:
        logger.info("No snipe opportunities found")

    # 4. Check watchlist
    logger.info("Phase 3: Checking watchlist alerts...")
    alerts = analysis.check_watchlist_alerts()
    if alerts:
        logger.info(f"Found {len(alerts)} watchlist alerts!")
        for a in alerts:
            logger.info(f"  {a['message']}")
        notifications.send_watchlist_alerts(alerts)
    else:
        logger.info("No watchlist alerts triggered")

    # 5. Summary
    summary = analysis.get_market_summary()
    logger.info(f"Database: {summary['total_players']} players, "
                f"{summary['total_price_snapshots']} price points")
    logger.info("Auto-run complete.")


if __name__ == "__main__":
    run()
