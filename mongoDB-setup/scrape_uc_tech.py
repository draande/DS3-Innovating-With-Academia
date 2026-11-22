import argparse
import os
import re
from urllib.parse import urljoin, urlsplit

import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://techtransfer.universityofcalifornia.edu/Default?RunSearch=true"
DETAIL_PATH = re.compile(r"/NCD/(\d+)\.html$", re.IGNORECASE)

def scrape_pages(max_pages):
    records = {}
    current_page = "[id$='_lblCurrentPageNum']"
    total_pages = "[id$='_lblTotalPages']"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded")

        last_page = int(page.locator(total_pages).inner_text())
        pages_to_scrape = min(max_pages, last_page)

        for page_number in range(1, pages_to_scrape + 1):
            page.wait_for_function(
                """({ selector, number }) =>
                    document.querySelector(selector)?.textContent.trim() === String(number)
                """,
                arg={"selector": current_page, "number": page_number},
            )

            page.locator(".technology-row a.tech-link").first.wait_for(state="attached")
            soup = BeautifulSoup(page.content(), "html.parser")
            previous_count = len(records)

            for row in soup.select(".technology-row"):
                link = row.select_one("a.tech-link[href]")
                if link is None:
                    continue

                source_url = urljoin(SEARCH_URL, link["href"])
                match = DETAIL_PATH.fullmatch(urlsplit(source_url).path)
                if match is None:
                    continue

                tech_id = match.group(1)
                title = link.get_text(" ", strip=True)
                if tech_id in records or not title:
                    continue

                summary_element = row.select_one(".tech-info")
                summary = summary_element.get_text(" ", strip=True) if summary_element else ""
                if summary.casefold() == "brief description not available":
                    summary = ""

                records[tech_id] = {
                    "_id": f"uc-techtransfer:{tech_id}",
                    "tech_id": tech_id,
                    "title": title,
                    "summary": summary or None,
                    "source_url": source_url,
                }

            added = len(records) - previous_count
            if added == 0:
                raise RuntimeError(f"Page {page_number} returned no new Tech IDs.")

            print(f"Page {page_number}/{last_page}: {added} new listings")

            if page_number < pages_to_scrape:
                time.sleep(1)
                page.locator(".pagination-block a[title='Next']").dispatch_event("click")

    return list(records.values())

def save_records(records):
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit("Add MONGODB_URI to your local .env before using --write.")

    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        collection = client["iwa"]["ip_records"]

        for record in records:
            fields = {key: value for key, value in record.items() if key != "_id"}
            collection.update_one(
                {"_id": record["_id"]},
                {"$set": fields},
                upsert=True,
            )

def main():
    parser = argparse.ArgumentParser(description="Scrape a sample of UC technology listings.")
    parser.add_argument("--write", action="store_true", help="Save listings to MongoDB Atlas.")
    parser.add_argument("--pages", type=int, default=1, help="Maximum pages to scrape.")
    args = parser.parse_args()

    if args.pages < 1:
        parser.error("--pages must be at least 1.")

    records = scrape_pages(args.pages)
    for record in records:
        print(f"{record['tech_id']} | {record['title']}")
        print(f"  {record['source_url']}")
        print(f"  {(record['summary'] or '(no summary)')[:160]}")

    if args.write:
        save_records(records)
        print(f"\nSaved {len(records)} records to iwa.ip_records.")

if __name__ == "__main__":
    main()