"""
MUT Tracker - Database Layer
SQLite database for storing player cards, price history, and snipe alerts.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "mut_tracker.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        -- Player cards master table
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mutgg_id TEXT UNIQUE NOT NULL,        -- e.g. "26-76017838"
            player_id TEXT,                        -- e.g. "17838"
            name TEXT NOT NULL,
            ovr INTEGER NOT NULL,
            position TEXT,
            archetype TEXT,
            program TEXT,
            team TEXT,
            speed INTEGER,
            quicksell_value INTEGER DEFAULT 0,
            url TEXT,
            date_added TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Price snapshots over time
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mutgg_id TEXT NOT NULL,
            platform TEXT DEFAULT 'ps',           -- 'ps', 'xbox', 'pc'
            price INTEGER NOT NULL,               -- current market price in coins
            lowest_bin INTEGER,                    -- lowest Buy It Now seen
            timestamp TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (mutgg_id) REFERENCES players(mutgg_id)
        );

        -- Watchlist - cards you want to track closely
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mutgg_id TEXT UNIQUE NOT NULL,
            target_buy_price INTEGER,             -- alert if price drops below this
            target_sell_price INTEGER,             -- alert if price rises above this
            notes TEXT,
            added_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (mutgg_id) REFERENCES players(mutgg_id)
        );

        -- Snipe log - profitable opportunities detected
        CREATE TABLE IF NOT EXISTS snipe_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mutgg_id TEXT NOT NULL,
            listed_price INTEGER NOT NULL,
            market_price INTEGER NOT NULL,
            profit_estimate INTEGER NOT NULL,      -- after 10% EA tax
            detected_at TEXT DEFAULT (datetime('now')),
            acted_on INTEGER DEFAULT 0,            -- did you buy it?
            FOREIGN KEY (mutgg_id) REFERENCES players(mutgg_id)
        );

        -- Set tracker - track set completion costs vs output value
        CREATE TABLE IF NOT EXISTS sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_name TEXT NOT NULL,
            input_cost INTEGER DEFAULT 0,          -- total cost of input cards
            output_value INTEGER DEFAULT 0,        -- value of completed set reward
            profit INTEGER DEFAULT 0,              -- output - input - tax
            last_calculated TEXT DEFAULT (datetime('now'))
        );

        -- Indexes for fast lookups
        CREATE INDEX IF NOT EXISTS idx_price_history_mutgg ON price_history(mutgg_id);
        CREATE INDEX IF NOT EXISTS idx_price_history_time ON price_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_players_ovr ON players(ovr);
        CREATE INDEX IF NOT EXISTS idx_players_position ON players(position);
        CREATE INDEX IF NOT EXISTS idx_players_program ON players(program);
        CREATE INDEX IF NOT EXISTS idx_snipe_log_time ON snipe_log(detected_at);
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialized.")


def upsert_player(player_data: dict):
    """Insert or update a player card."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO players (mutgg_id, player_id, name, ovr, position, archetype,
                             program, team, speed, quicksell_value, url, date_added, updated_at)
        VALUES (:mutgg_id, :player_id, :name, :ovr, :position, :archetype,
                :program, :team, :speed, :quicksell_value, :url, :date_added, datetime('now'))
        ON CONFLICT(mutgg_id) DO UPDATE SET
            name=excluded.name, ovr=excluded.ovr, position=excluded.position,
            archetype=excluded.archetype, program=excluded.program, team=excluded.team,
            speed=excluded.speed, quicksell_value=excluded.quicksell_value,
            url=excluded.url, updated_at=datetime('now')
    """, player_data)
    conn.commit()
    conn.close()


def add_price_snapshot(mutgg_id: str, price: int, lowest_bin: int = None, platform: str = "ps"):
    """Record a price data point."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO price_history (mutgg_id, platform, price, lowest_bin)
        VALUES (?, ?, ?, ?)
    """, (mutgg_id, platform, price, lowest_bin))
    conn.commit()
    conn.close()


def get_price_history(mutgg_id: str, limit: int = 100):
    """Get recent price history for a card."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM price_history
        WHERE mutgg_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (mutgg_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_to_watchlist(mutgg_id: str, target_buy: int = None, target_sell: int = None, notes: str = ""):
    """Add a card to the watchlist."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO watchlist (mutgg_id, target_buy_price, target_sell_price, notes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(mutgg_id) DO UPDATE SET
            target_buy_price=excluded.target_buy_price,
            target_sell_price=excluded.target_sell_price,
            notes=excluded.notes
    """, (mutgg_id, target_buy, target_sell, notes))
    conn.commit()
    conn.close()


def get_watchlist():
    """Get all watchlist items with latest prices."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT w.*, p.name, p.ovr, p.position, p.program, p.speed,
               (SELECT ph.price FROM price_history ph
                WHERE ph.mutgg_id = w.mutgg_id
                ORDER BY ph.timestamp DESC LIMIT 1) as latest_price,
               (SELECT ph.price FROM price_history ph
                WHERE ph.mutgg_id = w.mutgg_id
                ORDER BY ph.timestamp ASC LIMIT 1) as first_price
        FROM watchlist w
        JOIN players p ON w.mutgg_id = p.mutgg_id
        ORDER BY w.added_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_snipe(mutgg_id: str, listed_price: int, market_price: int):
    """Log a detected snipe opportunity."""
    tax = int(listed_price * 0.10)
    profit = market_price - listed_price - tax
    conn = get_connection()
    conn.execute("""
        INSERT INTO snipe_log (mutgg_id, listed_price, market_price, profit_estimate)
        VALUES (?, ?, ?, ?)
    """, (mutgg_id, listed_price, market_price, profit))
    conn.commit()
    conn.close()
    return profit


def get_snipe_log(limit: int = 50):
    """Get recent snipe opportunities."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.*, p.name, p.ovr, p.position, p.program
        FROM snipe_log s
        JOIN players p ON s.mutgg_id = p.mutgg_id
        ORDER BY s.detected_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_players(filters: dict = None):
    """Get players with optional filters."""
    conn = get_connection()
    query = "SELECT * FROM players WHERE 1=1"
    params = []

    if filters:
        if filters.get("min_ovr"):
            query += " AND ovr >= ?"
            params.append(filters["min_ovr"])
        if filters.get("position"):
            query += " AND position = ?"
            params.append(filters["position"])
        if filters.get("program"):
            query += " AND program = ?"
            params.append(filters["program"])
        if filters.get("name"):
            query += " AND name LIKE ?"
            params.append(f"%{filters['name']}%")

    query += " ORDER BY ovr DESC, speed DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price_movers(hours: int = 24, limit: int = 20):
    """Find biggest price changes in the last N hours."""
    conn = get_connection()
    rows = conn.execute("""
        WITH recent AS (
            SELECT mutgg_id, price,
                   ROW_NUMBER() OVER (PARTITION BY mutgg_id ORDER BY timestamp DESC) as rn
            FROM price_history
            WHERE timestamp >= datetime('now', ? || ' hours')
        ),
        earliest AS (
            SELECT mutgg_id, price as old_price FROM recent WHERE rn = (
                SELECT MAX(rn) FROM recent r2 WHERE r2.mutgg_id = recent.mutgg_id
            )
        ),
        latest AS (
            SELECT mutgg_id, price as new_price FROM recent WHERE rn = 1
        )
        SELECT p.name, p.ovr, p.position, p.program, p.mutgg_id,
               e.old_price, l.new_price,
               (l.new_price - e.old_price) as price_change,
               ROUND(((l.new_price - e.old_price) * 100.0 / e.old_price), 1) as pct_change
        FROM earliest e
        JOIN latest l ON e.mutgg_id = l.mutgg_id
        JOIN players p ON p.mutgg_id = e.mutgg_id
        WHERE e.old_price > 0
        ORDER BY ABS(l.new_price - e.old_price) DESC
        LIMIT ?
    """, (f"-{hours}", limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_undervalued_cards(threshold_pct: float = 20.0):
    """
    Find cards whose current price is significantly below their
    recent average — potential snipe targets.
    """
    conn = get_connection()
    rows = conn.execute("""
        WITH avg_prices AS (
            SELECT mutgg_id,
                   AVG(price) as avg_price,
                   MIN(price) as min_price,
                   MAX(price) as max_price,
                   COUNT(*) as data_points
            FROM price_history
            WHERE timestamp >= datetime('now', '-7 days')
            GROUP BY mutgg_id
            HAVING COUNT(*) >= 3
        ),
        latest AS (
            SELECT mutgg_id, price as current_price
            FROM price_history ph
            WHERE timestamp = (
                SELECT MAX(timestamp) FROM price_history
                WHERE mutgg_id = ph.mutgg_id
            )
        )
        SELECT p.name, p.ovr, p.position, p.program, p.mutgg_id,
               l.current_price, CAST(a.avg_price AS INTEGER) as avg_price,
               a.min_price, a.max_price,
               ROUND(((a.avg_price - l.current_price) * 100.0 / a.avg_price), 1) as discount_pct
        FROM avg_prices a
        JOIN latest l ON a.mutgg_id = l.mutgg_id
        JOIN players p ON p.mutgg_id = a.mutgg_id
        WHERE ((a.avg_price - l.current_price) * 100.0 / a.avg_price) >= ?
        ORDER BY discount_pct DESC
    """, (threshold_pct,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print("[DB] Tables ready.")
