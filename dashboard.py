"""
MUT Tracker Web Dashboard
Read-only Flask dashboard with tabs, search, and refresh.
Reads the same SQLite database the CLI writes to.

Run locally:
    pip install flask
    python dashboard.py
    open http://127.0.0.1:5000

In production this sits behind an Apache mod_ssl reverse proxy (see deploy/).
"""
from flask import Flask, render_template_string, jsonify, request
import sqlite3
import os

app = Flask(__name__)
DB_PATH = os.environ.get("MUT_DB_PATH", "mut_tracker.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        print(f"DB error: {e}")
        return default if default is not None else []


def table_exists(name):
    try:
        conn = get_conn()
        r = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        conn.close()
        return r is not None
    except Exception:
        return False


def col_exists(table, col):
    try:
        conn = get_conn()
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        conn.close()
        return any(r["name"] == col for r in rows)
    except Exception:
        return False


@app.route("/")
def index():
    return render_template_string(TEMPLATE)


@app.route("/api/stats")
def api_stats():
    def q():
        conn = get_conn()
        stats = {"players": 0, "watchlist": 0, "snipes": 0, "movers": 0}

        if table_exists("players"):
            stats["players"] = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        elif table_exists("price_history"):
            stats["players"] = conn.execute(
                "SELECT COUNT(DISTINCT mutgg_id) FROM price_history"
            ).fetchone()[0]

        if table_exists("watchlist"):
            stats["watchlist"] = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]

        try:
            import analysis
            stats["snipes"] = len(analysis.detect_snipes())
        except Exception:
            pass
        if stats["snipes"] == 0 and table_exists("snipe_log"):
            stats["snipes"] = conn.execute("SELECT COUNT(*) FROM snipe_log").fetchone()[0]
        elif stats["snipes"] == 0 and table_exists("price_history"):
            stats["snipes"] = conn.execute(
                "SELECT COUNT(*) FROM price_history WHERE price < lowest_bin * 0.95"
            ).fetchone()[0]

        if table_exists("price_history"):
            try:
                row = conn.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT mutgg_id FROM price_history
                        GROUP BY mutgg_id
                        HAVING (MAX(price) - MIN(price)) * 1.0 / NULLIF(MIN(price), 0) > 0.05
                    )
                """).fetchone()
                stats["movers"] = row[0] if row else 0
            except Exception:
                stats["movers"] = 0

        conn.close()
        return stats

    return jsonify(safe(q, {"players": 0, "watchlist": 0, "snipes": 0, "movers": 0}))


@app.route("/api/watchlist")
def api_watchlist():
    def q():
        conn = get_conn()
        if table_exists("players") and col_exists("watchlist", "target_buy_price"):
            rows = conn.execute("""
                SELECT w.mutgg_id, p.name, p.ovr, p.position, p.program,
                       w.target_buy_price, w.target_sell_price, w.notes,
                       (SELECT ph.price FROM price_history ph
                        WHERE ph.mutgg_id = w.mutgg_id
                        ORDER BY ph.timestamp DESC LIMIT 1) as latest_price
                FROM watchlist w
                LEFT JOIN players p ON w.mutgg_id = p.mutgg_id
                ORDER BY w.added_at DESC
            """).fetchall()
        elif col_exists("watchlist", "target_buy_price"):
            rows = conn.execute("""
                SELECT mutgg_id, NULL as name, NULL as ovr, NULL as position, NULL as program,
                       target_buy_price, target_sell_price, notes,
                       NULL as latest_price
                FROM watchlist
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT mutgg_id, NULL as name, NULL as ovr, NULL as position, NULL as program,
                       target_buy as target_buy_price, target_sell as target_sell_price, notes,
                       NULL as latest_price
                FROM watchlist
            """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    return jsonify(safe(q, []))


@app.route("/api/snipes")
def api_snipes():
    def q():
        # Preferred path: run the same live detection the CLI uses (7-day average, 10% tax).
        try:
            import analysis
            live = analysis.detect_snipes()
            if live:
                return [{
                    "mutgg_id": s["mutgg_id"], "name": s["name"], "ovr": s["ovr"],
                    "position": s["position"], "program": s["program"],
                    "listed_price": s["current_price"], "market_price": s["avg_price"],
                    "profit_estimate": s["est_profit"], "detected_at": None,
                } for s in live]
        except Exception as e:
            print(f"analysis unavailable, falling back to tables: {e}")
        conn = get_conn()
        if table_exists("snipe_log") and table_exists("players"):
            rows = conn.execute("""
                SELECT s.mutgg_id, p.name, p.ovr, p.position, p.program,
                       s.listed_price, s.market_price, s.profit_estimate, s.detected_at
                FROM snipe_log s
                LEFT JOIN players p ON s.mutgg_id = p.mutgg_id
                ORDER BY s.detected_at DESC
                LIMIT 25
            """).fetchall()
        elif table_exists("snipe_log"):
            rows = conn.execute("""
                SELECT mutgg_id, NULL as name, NULL as ovr, NULL as position, NULL as program,
                       listed_price, market_price, profit_estimate, detected_at
                FROM snipe_log ORDER BY detected_at DESC LIMIT 25
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT mutgg_id, NULL as name, NULL as ovr, NULL as position, NULL as program,
                       price as listed_price, lowest_bin as market_price,
                       (lowest_bin - price - CAST(price * 0.10 AS INTEGER)) as profit_estimate,
                       timestamp as detected_at
                FROM price_history
                WHERE price < lowest_bin * 0.95
                ORDER BY timestamp DESC LIMIT 25
            """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    return jsonify(safe(q, []))


@app.route("/api/players")
def api_players():
    search = request.args.get("q", "").strip()

    def q():
        conn = get_conn()
        if table_exists("players"):
            if search:
                like = f"%{search.lower()}%"
                rows = conn.execute("""
                    SELECT mutgg_id, name, ovr, position, program, speed
                    FROM players
                    WHERE LOWER(name) LIKE ? OR LOWER(position) LIKE ? OR LOWER(program) LIKE ?
                    ORDER BY ovr DESC LIMIT 50
                """, (like, like, like)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT mutgg_id, name, ovr, position, program, speed
                    FROM players ORDER BY ovr DESC LIMIT 50
                """).fetchall()
        else:
            rows = conn.execute("""
                SELECT DISTINCT mutgg_id, NULL as name, NULL as ovr, NULL as position,
                       NULL as program, NULL as speed
                FROM price_history LIMIT 50
            """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    return jsonify(safe(q, []))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MUT Tracker Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: #0a0e1a; color: #e8eaf0; min-height: 100vh; padding: 24px; }
  .header { border-bottom: 2px solid #ff8800; padding-bottom: 12px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
  .header h1 { color: #ff8800; font-size: 28px; letter-spacing: 1px; }
  .badge { background: #1d4d2c; color: #4ade80; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; }
  .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid #2a3447; flex-wrap: wrap; }
  .tab { background: none; border: none; color: #8a93a8; padding: 12px 18px; cursor: pointer; font-size: 14px; font-weight: 600; border-bottom: 3px solid transparent; transition: all 0.15s; font-family: inherit; }
  .tab:hover { color: #e8eaf0; }
  .tab.active { color: #ff8800; border-bottom-color: #ff8800; }
  .toolbar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
  .btn { background: #ff8800; color: #0a0e1a; border: none; padding: 9px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 13px; font-family: inherit; }
  .btn:hover { background: #ff9d2a; }
  .search { background: #121826; border: 1px solid #2a3447; color: #e8eaf0; padding: 9px 12px; border-radius: 6px; font-size: 13px; flex: 1; max-width: 320px; font-family: inherit; }
  .search:focus { outline: none; border-color: #ff8800; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #121826; border: 1px solid #2a3447; border-radius: 8px; padding: 18px; }
  .card h2 { color: #ff8800; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px; }
  .stat { font-size: 32px; font-weight: 700; }
  .stat.snipe { color: #4ade80; }
  .stat-sub { color: #8a93a8; font-size: 12px; margin-top: 4px; }
  .panel { background: #121826; border: 1px solid #2a3447; border-radius: 8px; padding: 20px; overflow-x: auto; }
  .panel h2 { color: #ff8800; font-size: 14px; text-transform: uppercase; margin-bottom: 14px; letter-spacing: 0.5px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid #2a3447; font-size: 13px; white-space: nowrap; }
  th { color: #8a93a8; font-weight: 600; font-size: 11px; text-transform: uppercase; }
  td.num { font-variant-numeric: tabular-nums; }
  tr:hover { background: rgba(255,136,0,0.04); }
  .pill { background: #1a2332; color: #8a93a8; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
  .pill.green { background: #1d4d2c; color: #4ade80; }
  .pill.amber { background: #4d3a1d; color: #fbbf24; }
  .empty { text-align: center; color: #5a627a; padding: 30px; font-style: italic; }
  .view { display: none; }
  .view.active { display: block; }
  .loading { color: #8a93a8; padding: 14px; text-align: center; font-size: 13px; }
  .updated { color: #4ade80; font-size: 12px; margin-left: 10px; }
  .footer { text-align: center; color: #5a627a; font-size: 12px; margin-top: 28px; padding-top: 14px; border-top: 1px solid #2a3447; }
</style>
</head>
<body>
  <div class="header">
    <h1>MUT TRACKER</h1>
    <span class="badge">LIVE</span>
  </div>

  <div class="grid">
    <div class="card"><h2>Tracked Players</h2><div class="stat" id="stat-players">-</div><div class="stat-sub">in database</div></div>
    <div class="card"><h2>Watchlist</h2><div class="stat" id="stat-watchlist">-</div><div class="stat-sub">active alerts</div></div>
    <div class="card"><h2>Snipe Opportunities</h2><div class="stat snipe" id="stat-snipes">-</div><div class="stat-sub">below market</div></div>
    <div class="card"><h2>Price Movers</h2><div class="stat" id="stat-movers">-</div><div class="stat-sub">5%+ change</div></div>
  </div>

  <div class="tabs">
    <button class="tab active" data-tab="overview">Overview</button>
    <button class="tab" data-tab="snipes">Snipes</button>
    <button class="tab" data-tab="watchlist">Watchlist</button>
    <button class="tab" data-tab="players">Player Search</button>
  </div>

  <div class="toolbar">
    <button class="btn" id="refresh">Refresh Data</button>
    <span id="last-updated" class="updated"></span>
  </div>

  <div id="view-overview" class="view active">
    <div class="panel"><h2>Top Snipe Opportunities</h2><div id="overview-snipes"><div class="loading">Loading...</div></div></div>
  </div>
  <div id="view-snipes" class="view">
    <div class="panel"><h2>Snipe Opportunities</h2><div id="snipes-table"><div class="loading">Loading...</div></div></div>
  </div>
  <div id="view-watchlist" class="view">
    <div class="panel"><h2>Active Watchlist</h2><div id="watchlist-table"><div class="loading">Loading...</div></div></div>
  </div>
  <div id="view-players" class="view">
    <div class="panel">
      <h2>Player Search</h2>
      <div class="toolbar"><input class="search" id="search-input" placeholder="Search by name, position, or program..."></div>
      <div id="players-table"><div class="loading">Type to search, or showing top 50 by OVR</div></div>
    </div>
  </div>

  <div class="footer">MUT Tracker · SQLite · Flask · Prices factor in EA's 10% auction tax</div>

<script>
const fmt = n => n == null ? "-" : Number(n).toLocaleString();
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const setHTML = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };

document.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("view-" + btn.dataset.tab).classList.add("active");
  if (btn.dataset.tab === "players") loadPlayers("");
}));

async function loadStats() {
  try {
    const d = await (await fetch("/api/stats")).json();
    for (const k of ["players", "watchlist", "snipes", "movers"]) document.getElementById("stat-" + k).textContent = fmt(d[k]);
  } catch (e) { console.error(e); }
}

function pill(v) { return v ? '<span class="pill">' + esc(v) + '</span>' : "-"; }

function snipeRowsHTML(rows, limit) {
  if (!rows.length) return '<div class="empty">No snipes detected. Run <code>python main.py scrape</code> to populate.</div>';
  const data = limit ? rows.slice(0, limit) : rows;
  let html = '<table><thead><tr><th>Player</th><th>OVR</th><th>Pos</th><th>Program</th><th>Listed</th><th>Market</th><th>Profit</th></tr></thead><tbody>';
  for (const s of data) {
    const profit = s.profit_estimate || 0;
    html += `<tr><td>${esc(s.name || s.mutgg_id)}</td><td class="num">${esc(s.ovr || "-")}</td><td>${pill(s.position)}</td><td>${esc(s.program || "-")}</td>` +
      `<td class="num">${fmt(s.listed_price)}</td><td class="num">${fmt(s.market_price)}</td><td class="num"><span class="${profit > 0 ? "pill green" : "pill amber"}">${fmt(profit)}</span></td></tr>`;
  }
  return html + '</tbody></table>';
}

async function loadSnipes() {
  try {
    const d = await (await fetch("/api/snipes")).json();
    setHTML("snipes-table", snipeRowsHTML(d));
    setHTML("overview-snipes", snipeRowsHTML(d, 5));
  } catch (e) { console.error(e); }
}

async function loadWatchlist() {
  try {
    const d = await (await fetch("/api/watchlist")).json();
    if (!d.length) { setHTML("watchlist-table", '<div class="empty">Watchlist empty.</div>'); return; }
    let html = '<table><thead><tr><th>Player</th><th>OVR</th><th>Pos</th><th>Program</th><th>Latest</th><th>Target Buy</th><th>Target Sell</th><th>Notes</th></tr></thead><tbody>';
    for (const w of d) {
      html += `<tr><td>${esc(w.name || w.mutgg_id)}</td><td class="num">${esc(w.ovr || "-")}</td><td>${pill(w.position)}</td><td>${esc(w.program || "-")}</td>` +
        `<td class="num">${fmt(w.latest_price)}</td><td class="num">${fmt(w.target_buy_price)}</td><td class="num">${fmt(w.target_sell_price)}</td><td>${esc(w.notes || "")}</td></tr>`;
    }
    setHTML("watchlist-table", html + '</tbody></table>');
  } catch (e) { console.error(e); }
}

async function loadPlayers(query) {
  try {
    const d = await (await fetch("/api/players?q=" + encodeURIComponent(query || ""))).json();
    if (!d.length) { setHTML("players-table", '<div class="empty">No players match.</div>'); return; }
    let html = '<table><thead><tr><th>Name</th><th>OVR</th><th>Pos</th><th>Program</th><th>Speed</th></tr></thead><tbody>';
    for (const p of d) {
      html += `<tr><td>${esc(p.name || p.mutgg_id)}</td><td class="num">${esc(p.ovr || "-")}</td><td>${pill(p.position)}</td><td>${esc(p.program || "-")}</td><td class="num">${esc(p.speed || "-")}</td></tr>`;
    }
    setHTML("players-table", html + '</tbody></table>');
  } catch (e) { console.error(e); }
}

let searchTimer;
document.getElementById("search-input").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadPlayers(e.target.value), 200);
});

function refreshAll() {
  loadStats(); loadSnipes(); loadWatchlist();
  document.getElementById("last-updated").textContent = "Updated " + new Date().toLocaleTimeString();
}
document.getElementById("refresh").addEventListener("click", refreshAll);
refreshAll();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
