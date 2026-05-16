"""
MAPNAI — agents/reddit_fetcher.py
Agent 1c: Reddit Social Signals Fetcher
Uses PRAW to pull top/hot posts from configured finance, geo, tech, health subreddits.
Converts posts into RawArticle objects with social metadata.
"""

from typing import List, Optional
import praw
from praw.exceptions import APIException, ClientException

from config.settings import settings
from config.sources import REDDIT_SOURCES, RedditSource
from utils.models import RawArticle, SourceType, Domain
from utils.logger import logger


def _get_reddit_client() -> Optional[praw.Reddit]:
    """Initialize PRAW Reddit client. Returns None if credentials missing."""
    if not all([
        settings.reddit_client_id,
        settings.reddit_client_secret,
        settings.reddit_client_id != "your_reddit_client_id",
    ]):
        logger.warning("[Reddit] API credentials not configured — skipping Reddit ingestion.")
        return None

    try:
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            read_only=True,
        )
        # Light test to verify connectivity
        reddit.user.me()  # returns None for read-only, but tests auth
        return reddit
    except ClientException as e:
        logger.error(f"[Reddit] Client error (check credentials): {e}")
        return None
    except Exception as e:
        logger.warning(f"[Reddit] Init warning: {e}")
        # Return client anyway — praw lazy-loads
        try:
            return praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
                read_only=True,
            )
        except Exception:
            return None


def fetch_subreddit(
    reddit: praw.Reddit,
    source: RedditSource,
) -> List[RawArticle]:
    """
    Fetch hot+top posts from a subreddit.
    Filters for posts with meaningful text content (selftext) or news links.
    """
    if not source.active:
        return []

    articles: List[RawArticle] = []

    try:
        subreddit = reddit.subreddit(source.subreddit)
        # Combine hot and top-day for diversity
        seen_ids: set = set()

        for post in subreddit.hot(limit=source.post_limit):
            if post.id in seen_ids:
                continue
            seen_ids.add(post.id)

            title = post.title.strip()
            # Use selftext for self posts, or title + flair for link posts
            body = post.selftext.strip() if post.selftext else post.title
            url  = post.url

            if not title:
                continue

            from utils.text_cleaner import normalize_timestamp
            articles.append(RawArticle(
                title=title,
                body=body if body else title,
                url=url,
                source_name=f"r/{source.subreddit}",
                source_type=SourceType.REDDIT,
                domain=Domain(source.domain),
                published_at=normalize_timestamp(post.created_utc),
                language="en",
                raw_metadata={
                    "score":          post.score,
                    "num_comments":   post.num_comments,
                    "subreddit":      source.subreddit,
                    "post_id":        post.id,
                    "flair":          post.link_flair_text,
                    "upvote_ratio":   post.upvote_ratio,
                    "is_self":        post.is_self,
                },
            ))

        logger.info(f"[Reddit] Fetched {len(articles)} posts from r/{source.subreddit}")

    except APIException as e:
        logger.error(f"[Reddit] API exception for r/{source.subreddit}: {e}")
    except Exception as e:
        logger.error(f"[Reddit] Error fetching r/{source.subreddit}: {e}")

    return articles


def fetch_all_reddit(
    sources: List[RedditSource] = None,
) -> List[RawArticle]:
    """
    Fetch all configured subreddits.
    Returns combined list of RawArticle objects.
    """
    sources = sources or REDDIT_SOURCES
    reddit  = _get_reddit_client()

    if reddit is None:
        return []

    all_articles: List[RawArticle] = []
    for source in sources:
        try:
            articles = fetch_subreddit(reddit, source)
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"[Reddit] Critical error on r/{source.subreddit}: {e}")

    logger.info(f"[Reddit] Total fetched: {len(all_articles)} posts")
    return all_articles
