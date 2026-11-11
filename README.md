# MUT Tracker

Market intelligence for Madden Ultimate Team. Scrapes player data from MUT.gg, tracks price history in SQLite, flags cards listed well below their 7-day average (with EA's 10% auction tax priced in), watches your targets, and pings Discord when something hits. Comes with a CLI and a read-only Flask dashboard.

Built as a personal tool, then used as the application under test for a Cloud Security course project: deployed to AWS EC2 behind Apache with TLS, encrypted EBS, least-privilege IAM, and CloudTrail. The deployment files are in `deploy/`.

## Architecture

```
MUT.gg  --[scraper.py / price_scraper.py]-->  SQLite (mut_tracker.db)
                                                   |
                                        [analysis.py] snipe detection,
                                        watchlist alerts, price movers,
                                        set profitability, training value
                                                   |
                              +--------------------+--------------------+
                              |                                         |
                      [main.py] CLI                          [dashboard.py] Flask
                      [auto_run.py] cron runner              4 tabs, search, refresh
                      [notifications.py] Discord webhooks
```

| File | What it does |
|------|--------------|
| `database.py` | SQLite schema and queries: players, price_history, watchlist, snipe_log, sets |
| `scraper.py` | requests + BeautifulSoup scraper for MUT.gg player pages (name, OVR, position, program, speed) |
| `price_scraper.py` | Optional Selenium scraper for prices, which MUT.gg renders with JavaScript |
| `analysis.py` | Snipe detection against the 7-day average, profit after 10% tax, watchlist alerts, movers, set and training math |
| `notifications.py` | Discord webhook alerts |
| `auto_run.py` | Scrape, analyze, alert on a schedule (cron) |
| `main.py` | CLI entry point |
| `dashboard.py` | Read-only Flask dashboard over the same database |
| `deploy/` | EC2 deployment script (Apache + mod_ssl reverse proxy, systemd services) and a least-privilege IAM policy |

## Quick start

```bash
pip install -r requirements.txt

python main.py demo          # loads 10 players with 7 days of simulated prices and two planted snipes
python main.py report        # full market report
python main.py snipes        # snipe opportunities
python main.py movers        # 24h price movers
python main.py search hill   # search players
python main.py training      # quicksell vs auction recommendations
```

Dashboard:

```bash
python dashboard.py
# open http://127.0.0.1:5000
```

## Live data

```bash
python main.py scrape --pages 5                     # player data from MUT.gg
python main.py scrape --pages 10 --min-ovr 95 --details
```

MUT.gg loads prices with JavaScript, so there are two ways to get price history in:

```bash
# Manual: log a price you saw in-game or on the site
python main.py price 26-76017838 480000
python main.py price 26-76017838                    # view history for that card

# Automatic: headless Chrome via Selenium (pip install selenium, Chrome installed)
python main.py price 26-76017838 --auto
python main.py prices --watchlist-only
```

## Watchlist and alerts

```bash
python main.py watch 26-76017838 --buy 500000 --sell 900000 --notes "Tyreek Sugar Rush"
python main.py watchlist
```

Alerts fire the moment a logged or scraped price crosses a target. To get them on your phone, create a Discord webhook and set:

```bash
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
```

## Automation

```bash
crontab -e
*/30 * * * * cd /path/to/mut-tracker && python auto_run.py >> logs/auto.log 2>&1
```

## How snipe detection works

A card is flagged when its latest price is at least 15% below its 7-day average and the trade is still profitable after EA's 10% auction house tax:

```
profit = avg_price * 0.90 - current_price
```

Both numbers come from `price_history`, so detection only works once there is price data for a card (demo data, manual logging, or the Selenium scraper).

## Deploying to AWS (the Cloud Security project)

`deploy/deploy.sh` sets up an Amazon Linux 2023 instance: installs Apache with mod_ssl, generates a self-signed certificate, configures an HTTP to HTTPS redirect and a reverse proxy to the Flask app, and registers the dashboard as a systemd service. The security model, in layers:

1. Security group: SSH restricted to one IP, only 80 and 443 open to the world
2. Encrypted EBS root volume (KMS)
3. TLS termination at Apache, HSTS and security headers, Flask bound to localhost only
4. IAM: a limited user with an explicit deny policy (`deploy/limited-user-policy.json`) to demonstrate least privilege
5. CloudTrail audit logging

## Notes

Personal-use tool. Be respectful with request rates against MUT.gg (the scraper sleeps between pages). The database file and any `.env` are gitignored.
