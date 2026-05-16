"""
MAPNAI — agents/bluesky_fetcher.py
Agent 1c: Bluesky Firehose Social Signal Fetcher

Connects to the public Bluesky Firehose WebSocket endpoint:
  wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos

Zero auth · Zero cost · Zero signup required.

The firehose emits a continuous stream of DAG-CBOR encoded ATProto
"#commit" messages. We decode each frame, extract app.bsky.feed.post
records and convert them to RawArticle objects.

Dependencies (add to requirements.txt if not present):
  websocket-client>=1.6.0
  cbor2>=5.4.0
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

try:
    import cbor2
except ImportError:  # pragma: no cover
    cbor2 = None  # type: ignore

try:
    import websocket
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore

from config.settings import settings
from utils.models import RawArticle, SourceType, Domain
from utils.logger import logger


# ── Bluesky post lexicon type ─────────────────────────────────
_FEED_POST_TYPE = "app.bsky.feed.post"


def _decode_frame(raw_bytes: bytes) -> Optional[dict]:
    """
    Decode a single firehose WebSocket frame.

    Each frame is a CBOR-encoded envelope:
      { "$type": "#commit" | "#handle" | ..., "blocks": <CAR bytes>, ... }

    We only process #commit frames and look for post records inside
    the `ops` list (op.action == "create", op.path startswith "app.bsky.feed.post").
    """
    if cbor2 is None:
        return None
    try:
        # ATProto frames are double-encoded: header CBOR + body CBOR
        # The first CBOR value is a small header map; the second is the body.
        decoder = cbor2.CBORDecoder(memoryview(raw_bytes))
        _header = decoder.decode()  # {"op": 1}
        body    = decoder.decode()  # the actual commit envelope
        return body
    except Exception:
        return None


def fetch_bluesky_firehose(
    max_posts: int = None,
    timeout_seconds: int = 30,
) -> List[RawArticle]:
    """
    Connect to the Bluesky Firehose and collect up to *max_posts* posts.

    Args:
        max_posts:        Maximum number of posts to collect (default from settings).
        timeout_seconds:  Hard wall-clock timeout for the collection window.

    Returns:
        List of RawArticle objects ready for the preprocessing pipeline.
    """
    if cbor2 is None:
        logger.error("[Bluesky] cbor2 is not installed — run: pip install cbor2")
        return []
    if websocket is None:
        logger.error("[Bluesky] websocket-client is not installed — run: pip install websocket-client")
        return []

    max_posts = max_posts or settings.bluesky_max_posts
    url       = settings.bluesky_firehose_url

    articles: List[RawArticle] = []
    lock      = threading.Lock()
    done      = threading.Event()

    def _on_message(ws: "websocket.WebSocketApp", raw: bytes):  # noqa: F821
        nonlocal articles

        body = _decode_frame(raw)
        if not body:
            return

        # Only process commit events
        if body.get("$type") != "#commit" and body.get("t") != "#commit":
            return

        ops = body.get("ops", [])
        repo = body.get("repo", "unknown")

        for op in ops:
            if op.get("action") != "create":
                continue

            path: str = op.get("path", "")
            if not path.startswith("app.bsky.feed.post"):
                continue

            record = op.get("record") or {}

            # Some frames embed records directly inside ops
            text: str = record.get("text", "").strip()
            if not text or len(text) < 10:
                continue

            created_at_raw = record.get("createdAt", "")
            try:
                published_at = datetime.fromisoformat(
                    created_at_raw.replace("Z", "+00:00")
                )
            except Exception:
                published_at = datetime.now(timezone.utc)

            # Build a deterministic URL from the repo DID + rkey
            rkey = path.split("/")[-1]
            post_url = f"https://bsky.app/profile/{repo}/post/{rkey}"

            article = RawArticle(
                title=text[:200],          # first 200 chars as title
                body=text,
                url=post_url,
                source_name="Bluesky Firehose",
                source_type=SourceType.BLUESKY,
                domain=Domain.TECHNOLOGY,  # enrichment agent will reclassify
                published_at=published_at,
                language=record.get("langs", ["en"])[0] if record.get("langs") else "en",
                raw_metadata={
                    "repo":       repo,
                    "rkey":       rkey,
                    "path":       path,
                    "via":        "firehose",
                    "embed_type": record.get("embed", {}).get("$type") if record.get("embed") else None,
                    "tags":       [
                        t.get("tag") for t in record.get("tags", []) if t.get("tag")
                    ],
                },
            )

            with lock:
                articles.append(article)
                if len(articles) >= max_posts:
                    done.set()
                    ws.close()
                    return

    def _on_error(ws: "websocket.WebSocketApp", error):  # noqa: F821
        logger.warning(f"[Bluesky] WebSocket error: {error}")
        done.set()

    def _on_close(ws: "websocket.WebSocketApp", *_):  # noqa: F821
        done.set()

    def _on_open(ws: "websocket.WebSocketApp"):  # noqa: F821
        logger.info(f"[Bluesky] Firehose connected — collecting up to {max_posts} posts.")

    logger.info(f"[Bluesky] Connecting to {url}")

    ws_app = websocket.WebSocketApp(
        url,
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )

    thread = threading.Thread(
        target=ws_app.run_forever,
        kwargs={"ping_interval": 20, "ping_timeout": 10},
        daemon=True,
    )
    thread.start()

    # Wait until we have enough posts OR timeout fires
    done.wait(timeout=timeout_seconds)

    if not done.is_set():
        logger.warning("[Bluesky] Timeout reached — closing connection.")
        ws_app.close()
        done.wait(timeout=5)

    thread.join(timeout=5)

    logger.info(f"[Bluesky] Collected {len(articles)} posts from Firehose.")
    return articles


# ── Public entry-point (mirrors fetch_all_reddit interface) ───

def fetch_all_bluesky(max_posts: int = None) -> List[RawArticle]:
    """
    Fetch a batch of Bluesky Firehose posts.
    Drop-in replacement for fetch_all_reddit().
    """
    try:
        return fetch_bluesky_firehose(max_posts=max_posts)
    except Exception as e:
        logger.error(f"[Bluesky] Fatal error during firehose fetch: {e}")
        return []
