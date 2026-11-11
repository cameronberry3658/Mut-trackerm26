"""
MUT Tracker - Scraper Module
Scrapes player data and prices from MUT.gg.

MUT.gg uses JavaScript rendering for price data, so we use two strategies:
1. requests + BeautifulSoup for static player data (stats, programs, etc.)
2. Selenium for dynamic price data (requires Chrome/Chromium)

For personal use only — be respectful with request rates.
"""

import requests
from bs4 import BeautifulSoup
import time
import re
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.mut.gg"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Respectful delay between requests (seconds)
REQUEST_DELAY = 2.0


def _get_page(url: str) -> BeautifulSoup:
    """Fetch a page and return parsed BeautifulSoup object."""
    time.sleep(REQUEST_DELAY)
    logger.info(f"Fetching: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def scrape_player_list(page: int = 1, min_ovr: int = None, program: str = None) -> list:
    """
    Scrape the player listing page from MUT.gg.
    Returns a list of dicts with basic player info.

    URL pattern: https://www.mut.gg/players/?page=1
    """
    url = f"{BASE_URL}/players/?page={page}"
    if min_ovr:
        url += f"&ovr_min={min_ovr}"
    if program:
        url += f"&program={program}"

    soup = _get_page(url)
    players = []

    # MUT.gg player cards are <a> tags linking to individual player pages
    # They contain OVR, name, program, position, and key stats
    player_links = soup.find_all("a", href=re.compile(r"/players/\d+-[\w-]+/26-\d+/"))

    for link in player_links:
        try:
            href = link.get("href", "")
            # Extract mutgg_id from URL: /players/17838-tyreek-hill/26-76017838/
            match = re.search(r"/players/(\d+)-[\w-]+/(26-\d+)/", href)
            if not match:
                continue

            player_id = match.group(1)
            mutgg_id = match.group(2)

            # Extract text content
            text = link.get_text(separator="|", strip=True)
            parts = [p.strip() for p in text.split("|") if p.strip()]

            # Parse the card data from the text content
            # Typical format: OVR|99|FirstName|LastName|SPD|99|...|Program|Position - Archetype
            ovr = None
            name_parts = []
            position = None
            archetype = None
            program_name = None
            speed = None

            # Find OVR (first number after "OVR")
            for i, part in enumerate(parts):
                if part == "OVR" and i + 1 < len(parts):
                    try:
                        ovr = int(parts[i + 1])
                    except ValueError:
                        pass
                elif part == "SPD" and i + 1 < len(parts):
                    try:
                        speed = int(parts[i + 1])
                    except ValueError:
                        pass

            # Try to extract name — usually the 2 parts after OVR number
            ovr_idx = None
            for i, part in enumerate(parts):
                if part == "OVR":
                    ovr_idx = i
                    break

            if ovr_idx is not None and ovr_idx + 3 < len(parts):
                first_name = parts[ovr_idx + 2]
                last_name = parts[ovr_idx + 3]
                # Make sure these aren't stat labels
                if first_name not in ("SPD", "ACC", "AGI", "STR", "JMP", "TAK", "BSH"):
                    name_parts = [first_name, last_name]

            name = " ".join(name_parts) if name_parts else "Unknown"

            # Find position and archetype (usually last part like "WR - Deep Threat")
            for part in reversed(parts):
                if " - " in part:
                    pos_arch = part.split(" - ", 1)
                    position = pos_arch[0].strip()
                    archetype = pos_arch[1].strip() if len(pos_arch) > 1 else None
                    break

            # Program is typically the second-to-last meaningful text
            # before the position line
            for part in parts:
                if part in KNOWN_PROGRAMS:
                    program_name = part
                    break

            player = {
                "mutgg_id": mutgg_id,
                "player_id": player_id,
                "name": name,
                "ovr": ovr or 0,
                "position": position,
                "archetype": archetype,
                "program": program_name or "",
                "team": "",
                "speed": speed or 0,
                "quicksell_value": 0,
                "url": f"{BASE_URL}{href}",
                "date_added": None,
            }
            players.append(player)

        except Exception as e:
            logger.warning(f"Failed to parse player card: {e}")
            continue

    logger.info(f"Scraped {len(players)} players from page {page}")
    return players


def scrape_player_detail(player_url: str) -> dict:
    """
    Scrape detailed info from an individual player page.
    Returns dict with full stats, quicksell value, team, etc.
    """
    soup = _get_page(player_url)
    detail = {}

    # Get the full page text for parsing
    page_text = soup.get_text(separator="\n", strip=True)

    # Quicksell value
    qs_match = re.search(r"Quicksell Value\s*\n?\s*([\d,]+)\s*Coins", page_text)
    if qs_match:
        detail["quicksell_value"] = int(qs_match.group(1).replace(",", ""))

    # Team
    team_match = re.search(r"Team\s*\n?\s*(.+?)(?:\n|Height)", page_text)
    if team_match:
        detail["team"] = team_match.group(1).strip()

    # Date added
    date_match = re.search(r"Date Added\s*\n?\s*(\d{2}/\d{2}/\d{4})", page_text)
    if date_match:
        detail["date_added"] = date_match.group(1)

    # All stats
    stat_labels = [
        "SPD", "ACC", "AGI", "AWR", "STR", "JMP", "RET",
        "CTH", "CIT", "SRR", "MRR", "DRR", "SPC", "RLS",
        "CAR", "BCV", "JKM", "SPM", "TRK", "SFA", "COD", "BTK",
        "RBK", "RBF", "RBP", "IBL",
        "THP", "SAC", "MAC", "DAC", "PAC", "RUN",
        "TAK", "POW", "BSH", "PUR", "PRC", "MCV", "ZCV", "PRS",
        "PMV", "FMV", "BKS",
        "KPW", "KAC", "CKA"
    ]

    stats = {}
    for label in stat_labels:
        pattern = rf"\b{label}\b\s*\n?\s*(\d{{1,3}})"
        match = re.search(pattern, page_text)
        if match:
            stats[label.lower()] = int(match.group(1))

    detail["stats"] = stats
    return detail


def try_find_mutgg_api(player_url: str) -> dict:
    """
    Attempt to find MUT.gg's internal API endpoints by checking for
    JSON data embedded in the page or XHR-style API URLs.
    
    Many modern sites embed initial data in a <script> tag as JSON,
    which we can extract without needing Selenium.
    """
    time.sleep(REQUEST_DELAY)
    resp = requests.get(player_url, headers=HEADERS, timeout=15)
    
    # Look for embedded JSON data (Next.js __NEXT_DATA__ or similar)
    next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if next_data_match:
        try:
            data = json.loads(next_data_match.group(1))
            logger.info("Found __NEXT_DATA__ — site uses Next.js!")
            return data
        except json.JSONDecodeError:
            pass

    # Look for other common patterns
    # Nuxt.js: window.__NUXT__
    nuxt_match = re.search(r'window\.__NUXT__\s*=\s*({.*?});?\s*</script>', resp.text, re.DOTALL)
    if nuxt_match:
        logger.info("Found __NUXT__ data")
        return {"raw": nuxt_match.group(1)[:500]}

    # Generic JSON blob in script tags
    script_tags = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    for script in script_tags:
        if '"price"' in script or '"market_price"' in script or '"auction"' in script.lower():
            logger.info("Found script with price-related data!")
            return {"raw_script": script[:1000]}

    # Check for API-style URLs in JavaScript
    api_urls = re.findall(r'["\'](/api/[^"\']+)["\']', resp.text)
    if api_urls:
        logger.info(f"Found API endpoints: {api_urls[:5]}")
        return {"api_endpoints": list(set(api_urls))}

    logger.info("No embedded data found — site likely requires Selenium for price data")
    return {}


# Known MUT programs for matching
KNOWN_PROGRAMS = {
    "All-Madden", "All-Star Athletes", "April Fools", "Autumn",
    "Black History", "Blitz", "Breakouts", "Campus Heroes",
    "Collector's Series", "Core", "Crystal", "Field Pass",
    "Flashbacks", "Free Agency", "Game Time", "Gauntlet",
    "Genki Force", "Ghosts of MUT", "GOAT", "Hispanic Heritage",
    "Legends", "Most Feared", "NFL Combine", "NFL Honors",
    "NFL Rivalry", "Playoffs", "Pregame Access", "Ranked",
    "Redux", "Ring of Honor", "Rookie Premiere", "Rookies",
    "Sugar Rush", "Super Bowl", "Team Builders", "Team Captains",
    "Team Diamonds", "TOTW", "TOTY", "Training Camp",
    "Tribute", "Ultimate Legend", "Ultimate Legends",
    "Ghost of MUT Present Players", "Merry Mix-Up",
    "Stocking Stuffers", "Season 3 Field Pass", "Season 4 Field Pass",
    "Season 5 Field Pass", "Season 6 Field Pass", "Season 7 Field Pass",
}


if __name__ == "__main__":
    # Quick test
    print("=== Testing Player List Scrape ===")
    players = scrape_player_list(page=1)
    for p in players[:5]:
        print(f"  {p['ovr']} OVR {p['name']} ({p['position']}) - {p['program']}")

    if players:
        print(f"\n=== Testing Detail Scrape for {players[0]['name']} ===")
        detail = scrape_player_detail(players[0]["url"])
        print(f"  Team: {detail.get('team')}")
        print(f"  Quicksell: {detail.get('quicksell_value')}")
        print(f"  Stats: {detail.get('stats', {})}")

        print(f"\n=== Checking for API Endpoints ===")
        api_data = try_find_mutgg_api(players[0]["url"])
        print(f"  Found: {list(api_data.keys()) if api_data else 'Nothing'}")
