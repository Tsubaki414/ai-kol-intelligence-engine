"""
X (Twitter) API v2 client for the KOL pipeline.

Thin httpx wrapper with:
- Bearer token auth (loaded from .env; passed AS-IS, not URL-decoded — X quirk)
- Automatic rate-limit detection + wait
- Retry with exponential backoff on transient errors
- Pagination helpers for list endpoints

Usage:
    async with XClient() as x:
        user = await x.get_user_by_username("shawmakesmagic")
        following = await x.get_following(user["id"], max_total=500)
        tweets = await x.get_user_tweets(user["id"], max_total=20)
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.x.com/2"

# Load .env from project root (parent of pipeline/)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


class XAPIError(Exception):
    """Non-retryable X API error (4xx other than 429)."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"X API error {status}: {body[:200]}")


class XClient:
    """Async client for X API v2 with sensible defaults for the pipeline."""

    def __init__(self, bearer_token: Optional[str] = None, *, timeout: float = 30.0):
        token = (bearer_token or os.environ.get("X_BEARER_TOKEN", "")).strip()
        if not token:
            raise RuntimeError("X_BEARER_TOKEN not set in .env")
        # IMPORTANT: Bearer must be sent AS-IS (URL-encoded form kept).
        # Decoding %2B -> + or %3D -> = causes 401 Unauthorized. This is an X API quirk.
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "kol-intelligence-pipeline/0.1",
            },
            timeout=timeout,
        )

    async def __aenter__(self) -> "XClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """GET with 429 rate-limit handling and 5xx retry."""
        params = params or {}
        for attempt in range(4):
            try:
                r = await self._client.get(path, params=params)
            except (httpx.ReadTimeout, httpx.ConnectError) as e:
                if attempt == 3:
                    raise XAPIError(0, f"network error: {e}")
                await asyncio.sleep(2**attempt)
                continue

            if r.status_code == 200:
                return r.json()

            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", "0"))
                wait_sec = max(1, reset - int(time.time()) + 2)
                wait_sec = min(wait_sec, 900)  # cap at 15 min
                print(f"  [rate-limited] waiting {wait_sec}s until reset…")
                await asyncio.sleep(wait_sec)
                continue

            if 500 <= r.status_code < 600:
                await asyncio.sleep(2**attempt)
                continue

            raise XAPIError(r.status_code, r.text)

        raise XAPIError(0, "exhausted retries")

    # ---------- user endpoints ----------

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        username = username.lstrip("@")
        try:
            data = await self._get(
                f"/users/by/username/{username}",
                params={
                    "user.fields": "public_metrics,description,created_at,location,url,verified,profile_image_url"
                },
            )
            return data.get("data")
        except XAPIError as e:
            if e.status == 404:
                return None
            raise

    async def get_users_by_ids(self, ids: list[str]) -> list[dict]:
        """Batch lookup up to 100 users by id in one request."""
        if not ids:
            return []
        data = await self._get(
            "/users",
            params={
                "ids": ",".join(ids[:100]),
                "user.fields": "public_metrics,description,created_at,location,url,verified,profile_image_url",
            },
        )
        return data.get("data", [])

    async def get_user_tweets(self, user_id: str, *, max_total: int = 20) -> list[dict]:
        """Fetch user's recent tweets, paginated."""
        result: list[dict] = []
        next_token: Optional[str] = None
        while len(result) < max_total:
            remaining = max_total - len(result)
            batch = min(100, max(5, remaining))  # X min is 5
            params = {
                "max_results": batch,
                "tweet.fields": "created_at,public_metrics,lang,referenced_tweets",
            }
            if next_token:
                params["pagination_token"] = next_token
            data = await self._get(f"/users/{user_id}/tweets", params)
            result.extend(data.get("data", []))
            next_token = data.get("meta", {}).get("next_token")
            if not next_token:
                break
        return result[:max_total]

    async def get_following(self, user_id: str, *, max_total: int = 500) -> list[dict]:
        """Fetch the accounts a user is following. Paginates until max_total."""
        result: list[dict] = []
        next_token: Optional[str] = None
        while len(result) < max_total:
            remaining = max_total - len(result)
            batch = min(1000, max(1, remaining))
            params = {
                "max_results": batch,
                "user.fields": "public_metrics,description,verified",
            }
            if next_token:
                params["pagination_token"] = next_token
            data = await self._get(f"/users/{user_id}/following", params)
            result.extend(data.get("data", []))
            next_token = data.get("meta", {}).get("next_token")
            if not next_token:
                break
        return result[:max_total]

    async def get_followers(self, user_id: str, *, max_total: int = 500) -> list[dict]:
        """Fetch followers (same pagination model as get_following)."""
        result: list[dict] = []
        next_token: Optional[str] = None
        while len(result) < max_total:
            remaining = max_total - len(result)
            batch = min(1000, max(1, remaining))
            params = {
                "max_results": batch,
                "user.fields": "public_metrics,description,verified",
            }
            if next_token:
                params["pagination_token"] = next_token
            data = await self._get(f"/users/{user_id}/followers", params)
            result.extend(data.get("data", []))
            next_token = data.get("meta", {}).get("next_token")
            if not next_token:
                break
        return result[:max_total]

    # ---------- search endpoint ----------

    async def search_recent(self, query: str, *, max_total: int = 100) -> dict:
        """
        Search recent tweets (Method B: Keyword + AI Filter expansion).

        Returns the full response dict (with 'data', 'includes', 'meta') so callers can
        extract author info from includes.users.
        """
        tweets: list[dict] = []
        users: list[dict] = []
        next_token: Optional[str] = None
        while len(tweets) < max_total:
            remaining = max_total - len(tweets)
            batch = min(100, max(10, remaining))
            params = {
                "query": query,
                "max_results": batch,
                "tweet.fields": "created_at,public_metrics,lang,author_id",
                "expansions": "author_id",
                "user.fields": "public_metrics,description,verified",
            }
            if next_token:
                params["next_token"] = next_token
            data = await self._get("/tweets/search/recent", params)
            tweets.extend(data.get("data", []))
            users.extend(data.get("includes", {}).get("users", []))
            next_token = data.get("meta", {}).get("next_token")
            if not next_token:
                break
        return {"tweets": tweets[:max_total], "users": users}
