#!/usr/bin/env python3
"""
CUPE Local Union Email Scraper

This script scrapes email addresses from CUPE local union websites.
It navigates through the CUPE locals directory, visits each local's page,
follows external website links when available, and extracts email addresses.

Usage:
    python cupe_email_scraper.py --start-page 1 --num-pages 5
    python cupe_email_scraper.py --start-page 1 --all-pages
"""

import argparse
import csv
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://cupe.ca/locals/Cupe"
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


@dataclass
class LocalInfo:
    """Data class to store information about a CUPE local."""

    name: str
    cupe_page_url: str
    local_website_url: Optional[str] = None
    emails: list = field(default_factory=list)
    phone: Optional[str] = None
    address: Optional[str] = None
    error: Optional[str] = None


class CUPEEmailScraper:
    """Scraper for CUPE local union emails."""

    def __init__(self, headless: bool = True):
        """Initialize the scraper with a Selenium WebDriver."""
        self.driver = self._create_driver(headless)
        self.results: list[LocalInfo] = []
        self.wait = WebDriverWait(self.driver, 10)

    def _create_driver(self, headless: bool) -> webdriver.Chrome:
        """Create and configure Chrome WebDriver."""
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # Suppress logging
        options.add_argument("--log-level=3")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(30)
            return driver
        except WebDriverException as e:
            logger.error(f"Failed to create WebDriver: {e}")
            raise

    def get_page_url(self, page_num: int) -> str:
        """Generate URL for a specific page number."""
        if page_num == 1:
            return BASE_URL
        return f"{BASE_URL}?page={page_num - 1}"  # CUPE uses 0-indexed pages

    def get_total_pages(self) -> int:
        """Get the total number of pages in the directory."""
        self.driver.get(BASE_URL)
        time.sleep(2)

        try:
            # Look for the "last" pagination link
            last_link = self.driver.find_element(
                By.CSS_SELECTOR, "a[title='Go to last page']"
            )
            href = last_link.get_attribute("href")
            # Extract page number from URL like ?page=417
            match = re.search(r"page=(\d+)", href)
            if match:
                return int(match.group(1)) + 1  # Convert from 0-indexed
        except NoSuchElementException:
            pass

        # Fallback: count pagination links
        try:
            pager = self.driver.find_element(By.CLASS_NAME, "pager")
            page_links = pager.find_elements(By.TAG_NAME, "a")
            max_page = 1
            for link in page_links:
                text = link.text.strip()
                if text.isdigit():
                    max_page = max(max_page, int(text))
            return max_page
        except NoSuchElementException:
            return 1

    def get_locals_on_page(self, page_num: int) -> list[tuple[str, str]]:
        """Get all local links from a specific page."""
        url = self.get_page_url(page_num)
        logger.info(f"Fetching page {page_num}: {url}")
        self.driver.get(url)
        time.sleep(2)

        locals_list = []

        try:
            # Find all local links - they typically have /local/ in the href
            links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/local/']")

            for link in links:
                href = link.get_attribute("href")
                name = link.text.strip()

                # Filter to only actual local pages (not collective agreements, etc.)
                if (
                    href
                    and "/local/" in href
                    and "collective-agreement" not in href
                    and name
                ):
                    # Avoid duplicates
                    if (name, href) not in locals_list:
                        locals_list.append((name, href))

            logger.info(f"Found {len(locals_list)} locals on page {page_num}")

        except Exception as e:
            logger.error(f"Error getting locals from page {page_num}: {e}")

        return locals_list

    def extract_emails_from_page(self) -> list[str]:
        """Extract email addresses from the current page."""
        emails = set()

        # Method 1: Find mailto links
        try:
            mailto_links = self.driver.find_elements(
                By.CSS_SELECTOR, "a[href^='mailto:']"
            )
            for link in mailto_links:
                href = link.get_attribute("href")
                if href:
                    email = href.replace("mailto:", "").split("?")[0].strip()
                    if email:
                        emails.add(email.lower())
        except Exception:
            pass

        # Method 2: Search page source for email patterns
        try:
            page_source = self.driver.page_source
            found_emails = EMAIL_REGEX.findall(page_source)
            for email in found_emails:
                # Filter out common false positives
                if not any(
                    fp in email.lower()
                    for fp in [
                        "example.com",
                        "your-email",
                        "email@",
                        "test@",
                        "sentry",
                        "webpack",
                        ".png",
                        ".jpg",
                        ".gif",
                        ".css",
                        ".js",
                    ]
                ):
                    emails.add(email.lower())
        except Exception:
            pass

        # Method 3: Look for text that looks like email in specific elements
        try:
            # Common contact elements
            selectors = [
                ".contact",
                ".email",
                "#contact",
                ".footer",
                "[class*='contact']",
                "[class*='email']",
            ]
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        text = elem.text
                        found = EMAIL_REGEX.findall(text)
                        for email in found:
                            emails.add(email.lower())
                except Exception:
                    continue
        except Exception:
            pass

        return list(emails)

    def extract_phone_from_page(self) -> Optional[str]:
        """Extract phone number from the current page."""
        try:
            # Look for tel: links first
            tel_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
            for link in tel_links:
                href = link.get_attribute("href")
                if href:
                    return href.replace("tel:", "").strip()

            # Search for phone patterns in page text
            phone_pattern = re.compile(
                r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
            )
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            match = phone_pattern.search(page_text)
            if match:
                return match.group()
        except Exception:
            pass
        return None

    def get_local_website_url(self) -> Optional[str]:
        """Get the external local website URL from the CUPE local page."""
        try:
            # Look for "Visit your local web site" link
            links = self.driver.find_elements(By.PARTIAL_LINK_TEXT, "Visit your local")
            for link in links:
                href = link.get_attribute("href")
                if href and "cupe.ca" not in href:
                    return href

            # Alternative: look for external links in the content area
            links = self.driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")
            for link in links:
                href = link.get_attribute("href")
                if href and "cupe.ca" not in href and "facebook" not in href.lower():
                    # Check if it looks like a local union website
                    text = link.text.lower()
                    if any(
                        kw in text
                        for kw in ["visit", "website", "local", "web site"]
                    ):
                        return href
        except Exception:
            pass
        return None

    def scrape_local(self, name: str, cupe_url: str) -> LocalInfo:
        """Scrape information for a single local."""
        local_info = LocalInfo(name=name, cupe_page_url=cupe_url)

        try:
            # Visit the CUPE local page
            logger.info(f"Visiting CUPE page for: {name}")
            self.driver.get(cupe_url)
            time.sleep(2)

            # Get phone from CUPE page
            local_info.phone = self.extract_phone_from_page()

            # Get emails from CUPE page
            cupe_emails = self.extract_emails_from_page()
            local_info.emails.extend(cupe_emails)

            # Get external website URL
            local_info.local_website_url = self.get_local_website_url()

            # If there's an external website, visit it for more info
            if local_info.local_website_url:
                logger.info(f"Visiting local website: {local_info.local_website_url}")
                try:
                    self.driver.get(local_info.local_website_url)
                    time.sleep(3)

                    # Extract emails from the local website
                    local_emails = self.extract_emails_from_page()
                    for email in local_emails:
                        if email not in local_info.emails:
                            local_info.emails.append(email)

                    # Try common contact page URLs
                    contact_paths = [
                        "/contact",
                        "/contact-us",
                        "/contact.html",
                        "/contactus",
                        "/about/contact",
                        "/about-us",
                    ]
                    base_url = local_info.local_website_url.rstrip("/")

                    for path in contact_paths:
                        try:
                            contact_url = base_url + path
                            self.driver.get(contact_url)
                            time.sleep(2)

                            # Check if page loaded successfully (not 404)
                            if "404" not in self.driver.title.lower():
                                contact_emails = self.extract_emails_from_page()
                                for email in contact_emails:
                                    if email not in local_info.emails:
                                        local_info.emails.append(email)
                                # If we found emails on contact page, stop trying others
                                if contact_emails:
                                    break
                        except Exception:
                            continue

                except TimeoutException:
                    logger.warning(
                        f"Timeout loading local website: {local_info.local_website_url}"
                    )
                except Exception as e:
                    logger.warning(f"Error loading local website: {e}")

        except TimeoutException:
            local_info.error = "Timeout loading CUPE page"
            logger.warning(f"Timeout loading CUPE page for {name}")
        except Exception as e:
            local_info.error = str(e)
            logger.error(f"Error scraping {name}: {e}")

        # Log results
        if local_info.emails:
            logger.info(f"Found emails for {name}: {local_info.emails}")
        else:
            logger.info(f"No emails found for {name}")

        return local_info

    def scrape_pages(self, start_page: int, num_pages: Optional[int] = None):
        """
        Scrape locals from specified pages.

        Args:
            start_page: Page number to start from (1-indexed)
            num_pages: Number of pages to scrape. If None, scrape all remaining.
        """
        total_pages = self.get_total_pages()
        logger.info(f"Total pages available: {total_pages}")

        if start_page > total_pages:
            logger.error(
                f"Start page {start_page} exceeds total pages {total_pages}"
            )
            return

        if num_pages is None:
            end_page = total_pages
        else:
            end_page = min(start_page + num_pages - 1, total_pages)

        logger.info(f"Scraping pages {start_page} to {end_page}")

        for page_num in range(start_page, end_page + 1):
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing page {page_num} of {end_page}")
            logger.info(f"{'='*50}\n")

            # Get all locals on this page
            locals_on_page = self.get_locals_on_page(page_num)

            # Scrape each local on the page before moving to next page
            for i, (name, url) in enumerate(locals_on_page, 1):
                logger.info(
                    f"[Page {page_num}] Processing local {i}/{len(locals_on_page)}: {name}"
                )
                local_info = self.scrape_local(name, url)
                self.results.append(local_info)

                # Save intermediate results after each local
                self.save_results()

                # Be respectful to servers
                time.sleep(1)

            logger.info(f"Completed page {page_num}")

    def save_results(self, filename_prefix: str = "cupe_locals"):
        """Save results to both CSV and JSON files."""
        # Save as CSV
        csv_path = Path(f"{filename_prefix}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Name",
                    "CUPE Page URL",
                    "Local Website URL",
                    "Emails",
                    "Phone",
                    "Error",
                ]
            )
            for local in self.results:
                writer.writerow(
                    [
                        local.name,
                        local.cupe_page_url,
                        local.local_website_url or "",
                        "; ".join(local.emails),
                        local.phone or "",
                        local.error or "",
                    ]
                )

        # Save as JSON
        json_path = Path(f"{filename_prefix}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(local) for local in self.results],
                f,
                indent=2,
                ensure_ascii=False,
            )

        logger.info(f"Results saved to {csv_path} and {json_path}")

    def close(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape email addresses from CUPE local union websites."
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Page number to start from (1-indexed, default: 1)",
    )
    parser.add_argument(
        "--num-pages",
        type=int,
        default=None,
        help="Number of pages to scrape (default: all remaining)",
    )
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="Scrape all pages from start page to end",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser with visible window",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="cupe_locals",
        help="Output filename prefix (default: cupe_locals)",
    )

    args = parser.parse_args()

    # Handle headless flag
    headless = not args.no_headless

    # Handle all-pages flag
    num_pages = None if args.all_pages else args.num_pages

    logger.info("Starting CUPE Email Scraper")
    logger.info(f"Start page: {args.start_page}")
    logger.info(f"Num pages: {'all remaining' if num_pages is None else num_pages}")
    logger.info(f"Headless: {headless}")

    scraper = CUPEEmailScraper(headless=headless)

    try:
        scraper.scrape_pages(args.start_page, num_pages)
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Saving current results...")
    finally:
        scraper.save_results(args.output)
        scraper.close()

    # Print summary
    total_locals = len(scraper.results)
    locals_with_emails = sum(1 for r in scraper.results if r.emails)
    total_emails = sum(len(r.emails) for r in scraper.results)

    logger.info("\n" + "=" * 50)
    logger.info("SCRAPING COMPLETE")
    logger.info("=" * 50)
    logger.info(f"Total locals processed: {total_locals}")
    logger.info(f"Locals with emails found: {locals_with_emails}")
    logger.info(f"Total unique emails found: {total_emails}")
    logger.info(f"Results saved to: {args.output}.csv and {args.output}.json")


if __name__ == "__main__":
    main()
