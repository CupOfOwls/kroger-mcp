#!/usr/bin/env python3
"""
Kroger Discount Background Scanner

Runs via macOS launchd on Mon/Thu at 9:00 AM.
Scans watchlist and whole foods catalog for current deals.
Writes results to database for MCP server to read.
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Add src to path so we can import modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from kroger_api import KrogerAPI
from kroger_mcp.analytics.database import get_db_connection, ensure_initialized
from kroger_mcp.analytics.deals import record_price_observation

# Setup logging
log_dir = Path.home() / "Library/Logs/KrogerScanner"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=log_dir / "scanner.log",
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def scan_watchlist_for_deals():
    """Main scanning function"""
    logging.info("Starting discount scan...")

    # Get credentials from environment
    client_id = os.getenv("KROGER_CLIENT_ID")
    client_secret = os.getenv("KROGER_CLIENT_SECRET")

    if not client_id or not client_secret:
        logging.error("KROGER_CLIENT_ID or KROGER_CLIENT_SECRET not set")
        return

    # Initialize Kroger API
    try:
        api = KrogerAPI(
            client_id=client_id,
            client_secret=client_secret
        )
    except Exception as e:
        logging.error(f"Failed to initialize Kroger API: {e}")
        return

    # Get preferred location
    location_id = os.getenv("KROGER_PREFERRED_LOCATION")
    if not location_id:
        logging.error("No KROGER_PREFERRED_LOCATION set")
        return

    logging.info(f"Using location: {location_id}")

    # Initialize database
    try:
        ensure_initialized()
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        return

    # Get watchlist items
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            SELECT product_id, description, target_price
            FROM deal_watchlist
            ORDER BY priority DESC, last_checked_at ASC
            LIMIT 50
            """
        )
        watchlist = cursor.fetchall()
    except Exception as e:
        logging.error(f"Failed to get watchlist: {e}")
        conn.close()
        return
    finally:
        conn.close()

    logging.info(f"Scanning {len(watchlist)} watchlist items...")

    deals_found = []

    # Scan each item
    for item in watchlist:
        try:
            product_id = item["product_id"]
            description = item["description"]

            logging.info(f"Checking {product_id}: {description}")

            # Search for product by description
            results = api.product.search_products(
                term=description or product_id,
                location_id=location_id,
                limit=1
            )

            if not results or "data" not in results or not results["data"]:
                logging.warning(f"No results for {product_id}")
                continue

            product = results["data"][0]

            # Check if on sale
            if "items" in product and product["items"]:
                item_data = product["items"][0]
                pricing = item_data.get("price", {})
                regular = pricing.get("regular")
                promo = pricing.get("promo")

                if promo and regular and promo < regular:
                    savings = regular - promo

                    # Record price
                    try:
                        record_price_observation(
                            product_id=product_id,
                            regular_price=regular,
                            sale_price=promo,
                            location_id=location_id,
                            source="background_scan"
                        )
                        logging.info(f"Found deal: {description} - ${promo:.2f} (save ${savings:.2f})")
                    except Exception as e:
                        logging.warning(f"Failed to record price: {e}")

                    deals_found.append({
                        "product_id": product_id,
                        "description": description,
                        "regular_price": regular,
                        "sale_price": promo,
                        "savings": savings
                    })

            # Update last_checked_at
            try:
                conn = get_db_connection()
                conn.execute(
                    """
                    UPDATE deal_watchlist
                    SET last_checked_at = ?
                    WHERE product_id = ?
                    """,
                    (datetime.now().isoformat(), product_id)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logging.warning(f"Failed to update last_checked_at: {e}")

        except Exception as e:
            logging.error(f"Error scanning {item['product_id']}: {e}")
            continue

    # Save scan results
    if deals_found:
        try:
            save_scan_results(deals_found)
            logging.info(f"Scan complete. Found {len(deals_found)} deals")

            # Send notification
            send_notification(len(deals_found))
        except Exception as e:
            logging.error(f"Failed to save results: {e}")
    else:
        logging.info("Scan complete. No deals found")


def save_scan_results(deals: list):
    """Save scan results to database"""
    conn = get_db_connection()
    try:
        # Clear old results (keep last 7 days)
        conn.execute("DELETE FROM deal_scan_results WHERE scan_date < date('now', '-7 days')")

        # Insert new results
        scan_time = datetime.now().isoformat()
        scan_date = datetime.now().date().isoformat()

        for deal in deals:
            conn.execute(
                """
                INSERT INTO deal_scan_results
                (product_id, description, regular_price, sale_price,
                 savings_amount, scan_date, scan_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deal["product_id"],
                    deal["description"],
                    deal["regular_price"],
                    deal["sale_price"],
                    deal["savings"],
                    scan_date,
                    scan_time
                ),
            )

        conn.commit()
        logging.info(f"Saved {len(deals)} deals to database")
    finally:
        conn.close()


def send_notification(deal_count: int):
    """Send macOS notification"""
    import subprocess

    title = "Kroger Deals Found!"
    message = f"{deal_count} items on sale this week"

    script = f'display notification "{message}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False)
        logging.info("Notification sent")
    except Exception as e:
        logging.warning(f"Failed to send notification: {e}")


if __name__ == "__main__":
    try:
        scan_watchlist_for_deals()
    except Exception as e:
        logging.error(f"Scan failed: {e}", exc_info=True)
        sys.exit(1)
