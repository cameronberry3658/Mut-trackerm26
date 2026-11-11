"""
MUT Tracker - Price Scraper (Selenium)
Scrapes actual prices from MUT.gg player pages using a headless browser.

MUT.gg loads price data via JavaScript, so we need Selenium to render
the page and extract prices from the DOM.

Setup:
    pip install selenium

Chrome/Chromium must be installed. Selenium 4+ auto-downloads the driver.
"""

import re
import time
import logging
import database as db

logger = logging.getLogger(__name__)

# Delay between page loads to be respectful
PAGE_DELAY = 3.0


def _get_driver():
    """Create a headless Chrome browser instance."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(20)
    return driver


def scrape_player_price(player_url: str) -> dict:
    """
    Scrape price data from a single MUT.gg player page.

    Returns dict with:
        - price: current market price (int)
        - lowest_bin: lowest Buy It Now (int or None)
        - platform: 'ps', 'xbox', or 'pc'
    """
    if not player_url or player_url == "#":
        return {}

    driver = None
    try:
        driver = _get_driver()

        prices_url = player_url.rstrip("/") + "/"
        driver.get(prices_url)
        time.sleep(PAGE_DELAY)

        page_text = driver.page_source
        price_data = _extract_prices_from_html(page_text)

        if price_data.get("price"):
            logger.info(f"Price found: {price_data['price']:,}")
        else:
            logger.warning("Could not extract price from page")

        return price_data

    except Exception as e:
        logger.error(f"Selenium error: {e}")
        return {}
    finally:
        if driver:
            driver.quit()


def _extract_prices_from_html(html: str) -> dict:
    """
    Extract price data from rendered HTML.
    MUT.gg displays prices in various formats, so we try multiple patterns.
    """
    result = {"price": None, "lowest_bin": None, "platform": "ps"}

    price_patterns = [
        r'(?:Price|Market Price|Current Price|Avg Price)[:\s]*?([\d,]+)\s*(?:Coins)?',
        r'(?:PS|PlayStation|Xbox|PC)[:\s]*?([\d,]+)\s*(?:Coins)?',
        r'"price"\s*:\s*(\d+)',
        r'"market_price"\s*:\s*(\d+)',
        r'"avg_price"\s*:\s*(\d+)',
        r'data-price="(\d+)"',
        # Generic large number near price-related keywords
        r'(?:sale|sold|selling|listed|auction)[^<]{0,50}?([\d,]{4,12})',
    ]

    for pattern in price_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                price = int(price_str)
                if 100 < price < 50_000_000:  # sanity check
                    result["price"] = price
                    break
            except ValueError:
                continue

    bin_patterns = [
        r'(?:Lowest BIN|Low BIN|Min BIN)[:\s]*?([\d,]+)',
        r'"lowest_bin"\s*:\s*(\d+)',
        r'"low_bin"\s*:\s*(\d+)',
    ]

    for pattern in bin_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            bin_str = match.group(1).replace(",", "")
            try:
                result["lowest_bin"] = int(bin_str)
                break
            except ValueError:
                continue

    # Try to find embedded JSON data (Next.js, Nuxt, etc.)
    json_match = re.search(r'<script[^>]*>.*?"price"\s*:\s*(\d+).*?</script>', html, re.DOTALL)
    if json_match and not result["price"]:
        try:
            price = int(json_match.group(1))
            if 100 < price < 50_000_000:
                result["price"] = price
        except ValueError:
            pass

    return result


def scrape_prices_bulk(mutgg_ids: list) -> list:
    """
    Scrape prices for multiple players in one browser session.
    More efficient than opening/closing the browser for each player.
    """
    conn = db.get_connection()
    results = []
    driver = None

    try:
        driver = _get_driver()

        for mutgg_id in mutgg_ids:
            player = conn.execute(
                "SELECT * FROM players WHERE mutgg_id = ?", (mutgg_id,)
            ).fetchone()

            if not player or not player["url"] or player["url"] == "#":
                results.append({"mutgg_id": mutgg_id, "price": None, "error": "no URL"})
                continue

            try:
                url = player["url"].rstrip("/") + "/"
                driver.get(url)
                time.sleep(PAGE_DELAY)

                price_data = _extract_prices_from_html(driver.page_source)

                if price_data.get("price"):
                    db.add_price_snapshot(
                        mutgg_id,
                        price_data["price"],
                        price_data.get("lowest_bin")
                    )
                    print(f"  {player['ovr']:>3} {player['name']:<25} {price_data['price']:>10,} coins")
                else:
                    print(f"  {player['ovr']:>3} {player['name']:<25} -- no price found --")

                results.append({"mutgg_id": mutgg_id, **price_data})

            except Exception as e:
                logger.warning(f"Error scraping {player['name']}: {e}")
                results.append({"mutgg_id": mutgg_id, "price": None, "error": str(e)})
                continue

    except Exception as e:
        logger.error(f"Browser error: {e}")
    finally:
        if driver:
            driver.quit()
        conn.close()

    return results


if __name__ == "__main__":
    print("Testing price scraper...")
    test_url = "https://www.mut.gg/players/17838-tyreek-hill/26-76017838/"
    result = scrape_player_price(test_url)
    print(f"Result: {result}")
