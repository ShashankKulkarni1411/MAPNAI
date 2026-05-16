"""
MAPNAI — config/sources.py
Defines all ingestion sources: RSS feeds, API endpoints, subreddits,
government feeds, and scraper targets.
Add / remove sources here without touching any agent code.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RSSSource:
    name: str
    url: str
    domain: str          # finance | geopolitics | technology | health | supply_chain | general
    language: str = "en"
    active: bool = True


@dataclass
class RedditSource:
    subreddit: str
    domain: str
    post_limit: int = 25
    active: bool = True


@dataclass
class ScraperTarget:
    name: str
    url: str
    domain: str
    article_selector: str   # CSS selector for article links
    title_selector: str
    body_selector: str
    active: bool = True


# ── RSS Feeds — Finance ──────────────────────────────────────
FINANCE_RSS: List[RSSSource] = [
    RSSSource("Reuters Business",     "https://feeds.reuters.com/reuters/businessNews",        "finance"),
    RSSSource("Bloomberg Markets",    "https://feeds.bloomberg.com/markets/news.rss",          "finance"),
    RSSSource("CNBC Finance",         "https://www.cnbc.com/id/10000664/device/rss/rss.html",  "finance"),
    RSSSource("Financial Times",      "https://www.ft.com/rss/home",                           "finance"),
    RSSSource("Moneycontrol",         "https://www.moneycontrol.com/rss/latestnews.xml",       "finance"),
    RSSSource("Economic Times",       "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "finance"),
    RSSSource("Mint",                 "https://www.livemint.com/rss/markets",                  "finance"),
    RSSSource("MarketWatch",          "https://feeds.content.dowjones.io/public/rss/mw_topstories", "finance"),
    RSSSource("Seeking Alpha",        "https://seekingalpha.com/feed.xml",                     "finance"),
    RSSSource("Yahoo Finance",        "https://finance.yahoo.com/rss/topfinstories",           "finance"),
]

# ── RSS Feeds — Geopolitics ──────────────────────────────────
GEOPOLITICS_RSS: List[RSSSource] = [
    RSSSource("Reuters World",        "https://feeds.reuters.com/reuters/worldNews",           "geopolitics"),
    RSSSource("BBC World",            "http://feeds.bbci.co.uk/news/world/rss.xml",            "geopolitics"),
    RSSSource("Al Jazeera",           "https://www.aljazeera.com/xml/rss/all.xml",             "geopolitics"),
    RSSSource("Foreign Policy",       "https://foreignpolicy.com/feed/",                       "geopolitics"),
    RSSSource("The Diplomat",         "https://thediplomat.com/feed/",                         "geopolitics"),
    RSSSource("Council on Foreign Relations", "https://www.cfr.org/rss.xml",                  "geopolitics"),
    RSSSource("NDTV World",           "https://feeds.feedburner.com/ndtvnews-world-news",      "geopolitics"),
    RSSSource("The Wire",             "https://thewire.in/feed",                               "geopolitics"),
]

# ── RSS Feeds — Technology ───────────────────────────────────
TECHNOLOGY_RSS: List[RSSSource] = [
    RSSSource("TechCrunch",           "https://techcrunch.com/feed/",                          "technology"),
    RSSSource("The Verge",            "https://www.theverge.com/rss/index.xml",                "technology"),
    RSSSource("Wired",                "https://www.wired.com/feed/rss",                        "technology"),
    RSSSource("MIT Tech Review",      "https://www.technologyreview.com/feed/",                "technology"),
    RSSSource("Ars Technica",         "http://feeds.arstechnica.com/arstechnica/index",        "technology"),
    RSSSource("Hacker News",          "https://hnrss.org/frontpage",                           "technology"),
    RSSSource("VentureBeat",          "https://venturebeat.com/feed/",                         "technology"),
    RSSSource("AI News",              "https://www.artificialintelligence-news.com/feed/",     "technology"),
]

# ── RSS Feeds — Health ───────────────────────────────────────
HEALTH_RSS: List[RSSSource] = [
    RSSSource("WHO News",             "https://www.who.int/rss-feeds/news-english.xml",        "health"),
    RSSSource("Reuters Health",       "https://feeds.reuters.com/reuters/healthNews",          "health"),
    RSSSource("NIH News",             "https://www.nih.gov/news-events/news-releases/feed.xml","health"),
    RSSSource("CDC Media",            "https://tools.cdc.gov/api/v2/resources/media/132608.rss","health"),
    RSSSource("STAT News",            "https://www.statnews.com/feed/",                        "health"),
    RSSSource("Medscape",             "https://www.medscape.com/cx/rss/professional.xml",      "health"),
]

# ── RSS Feeds — Supply Chain ─────────────────────────────────
SUPPLY_CHAIN_RSS: List[RSSSource] = [
    RSSSource("Supply Chain Dive",    "https://www.supplychaindive.com/feeds/news/",           "supply_chain"),
    RSSSource("Logistics Management", "https://www.logisticsmgmt.com/rss/all",                 "supply_chain"),
    RSSSource("Reuters Commodities",  "https://feeds.reuters.com/reuters/companyNews",         "supply_chain"),
    RSSSource("Freightos",            "https://www.freightos.com/feed/",                       "supply_chain"),
]

# ── Government & Policy Sources ──────────────────────────────
GOVERNMENT_RSS: List[RSSSource] = [
    RSSSource("RBI Press Releases",   "https://www.rbi.org.in/Scripts/rss.aspx",               "finance"),
    RSSSource("IMF News",             "https://www.imf.org/en/News/rss?language=eng",          "finance"),
    RSSSource("World Bank",           "https://feeds.worldbank.org/worldbank/world/feeds/rss", "finance"),
    RSSSource("SEBI",                 "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRssFeed=yes", "finance"),
    RSSSource("US Fed Reserve",       "https://www.federalreserve.gov/feeds/press_all.xml",    "finance"),
    RSSSource("UN News",              "https://news.un.org/feed/subscribe/en/news/all/rss.xml","geopolitics"),
    RSSSource("WHO Outbreaks",        "https://www.who.int/feeds/entity/csr/don/en/rss.xml",   "health"),
    RSSSource("PIB India",            "https://pib.gov.in/RssMain.aspx",                       "geopolitics"),
]

# ── Reddit Sources ───────────────────────────────────────────
REDDIT_SOURCES: List[RedditSource] = [
    RedditSource("worldnews",         "geopolitics",    post_limit=30),
    RedditSource("economics",         "finance",        post_limit=25),
    RedditSource("finance",           "finance",        post_limit=25),
    RedditSource("technology",        "technology",     post_limit=25),
    RedditSource("artificial",        "technology",     post_limit=20),
    RedditSource("MachineLearning",   "technology",     post_limit=20),
    RedditSource("geopolitics",       "geopolitics",    post_limit=25),
    RedditSource("India",             "geopolitics",    post_limit=20),
    RedditSource("investing",         "finance",        post_limit=25),
    RedditSource("supplychain",       "supply_chain",   post_limit=15),
    RedditSource("coronavirus",       "health",         post_limit=15),
    RedditSource("health",            "health",         post_limit=15),
]

# ── Aggregated source list (all RSS) ─────────────────────────
ALL_RSS_SOURCES: List[RSSSource] = (
    FINANCE_RSS
    + GEOPOLITICS_RSS
    + TECHNOLOGY_RSS
    + HEALTH_RSS
    + SUPPLY_CHAIN_RSS
    + GOVERNMENT_RSS
)

# ── Domain keyword hints for auto-classification ─────────────
DOMAIN_KEYWORDS: dict = {
    "finance": [
        "bank", "stock", "market", "economy", "inflation", "gdp", "rbi", "fed",
        "interest rate", "currency", "investment", "ipo", "sebi", "imf",
        "fiscal", "monetary", "credit", "debt", "equity", "commodity",
    ],
    "geopolitics": [
        "war", "conflict", "sanction", "election", "government", "military",
        "diplomacy", "treaty", "nato", "un", "china", "russia", "india",
        "foreign policy", "trade war", "coup", "protest", "minister",
    ],
    "technology": [
        "ai", "artificial intelligence", "software", "startup", "silicon",
        "cybersecurity", "chip", "semiconductor", "cloud", "algorithm",
        "machine learning", "llm", "openai", "google", "apple", "microsoft",
    ],
    "health": [
        "disease", "vaccine", "pandemic", "virus", "hospital", "drug",
        "fda", "who", "outbreak", "clinical trial", "cancer", "therapy",
        "pharmaceutical", "health", "medical", "cdc",
    ],
    "supply_chain": [
        "supply chain", "logistics", "shipping", "port", "freight",
        "inventory", "manufacturing", "trade route", "tariff", "import",
        "export", "container", "warehouse", "procurement",
    ],
}
