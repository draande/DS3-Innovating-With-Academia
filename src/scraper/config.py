"""Constants and paths shared across the scraper modules."""

from pathlib import Path

# --- Source site -----------------------------------------------------------
BASE_URL = "https://techtransfer.universityofcalifornia.edu"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

# Article pages look like https://techtransfer.universityofcalifornia.edu/NCD/34887.html
ARTICLE_URL_PATTERN = r"/NCD/(\d+)\.html$"

# Generic client name (no personal/project details sent to the site).
USER_AGENT = "Mozilla/5.0 (compatible; academic-research-scraper/0.1)"

# --- Politeness / reliability ---------------------------------------------
# One request at a time with a pause between them keeps load on the site low
# (~3.8k pages -> roughly an hour end to end).
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5.0

# --- Local paths (follow the template's data/raw vs data/processed split) --
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

SITEMAP_PATH = RAW_DIR / "sitemap.xml"
HTML_DIR = RAW_DIR / "html"
FETCH_LOG_PATH = RAW_DIR / "fetch_log.csv"

CSV_DIR = PROCESSED_DIR / "uc_techtransfer"
