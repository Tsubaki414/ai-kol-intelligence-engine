"""
KOL Data Schema — single source of truth for scoring input/output.

This module defines the normalized data contract between the pipeline and the
three-layer scoring system (see scoring/scoring_spec.md v3 2026-04-09).

Usage:
    from scoring.schema import KolRaw, ScoredKol

    # Load from a dict (e.g., from JSON)
    kol = KolRaw.model_validate(raw_dict)

    # Score it
    from scoring.score_kol import score_kol
    result: ScoredKol = score_kol(kol)

    # Serialize
    result_dict = result.model_dump()
    result_json = result.model_dump_json(indent=2)

Design notes:
- All fields have defaults so partial data (e.g., no on-chain) validates.
- Optional = "not available for this KOL"; required = "scoring cannot run without it".
- The `KolRaw` shape is MORE normalized than any single existing pipeline file.
  An enrichment step merges classified_kols.json + core_tweets.json + graph_v1.json
  + Phase 1d outputs into a KolRaw. See scoring/schema.md for the mapping.
- `ScoredKol` stores three parallel scores (quality / cooperability / onchain)
  that are NEVER fused into a single overall number.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ============================================================
# Primitive literal types
# ============================================================

TierLiteral = Literal["Nano", "Micro", "Macro", "Mega"]

ContentClassLiteral = Literal[
    "retweet",
    "news_share",
    "meme_casual",
    "quote_with_commentary",
    "original_observation",
    "thread",
    "original_deep_analysis",
    "ai_generated_suspected",
]

TweetTypeLiteral = Literal["original", "retweet", "quote", "reply"]

ConfidenceLiteral = Literal["high", "medium", "low", "n/a"]

SentimentLiteral = Literal["bullish", "bearish", "neutral"]


# ============================================================
# Tweet-level data (one post)
# ============================================================


class PublicMetrics(BaseModel):
    """Per-tweet public metrics from X API v2 /users/:id/tweets `public_metrics` field.

    Note: `impression_count` (view count) is unreliable in X API Basic tier
    for non-owned accounts and is deliberately excluded. EQR uses only
    like/reply/retweet/quote counts (see scoring_spec.md §4.1).
    """

    like_count: int = 0
    reply_count: int = 0
    retweet_count: int = 0
    quote_count: int = 0


class ReferencedTweet(BaseModel):
    """An entry in a tweet's `referenced_tweets` array. Used to detect tweet type."""

    type: Literal["retweeted", "quoted", "replied_to"]
    id: str


class PostClassification(BaseModel):
    """Claude Phase 1d pre-classification of one post.

    This is produced by a one-shot Claude API call per KOL (batched for cost).
    Scoring functions CONSUME this; they do not call Claude themselves.
    """

    content_class: ContentClassLiteral
    is_ai_generated_suspected: bool = False
    sector: str = "other"
    is_ai_crypto_related: bool = False
    originality_score_raw: int = Field(ge=0, le=100, description="Claude's 0-100 originality judgment")
    promo_match: Optional[str] = Field(
        None, description='Detected sponsor phrase: "#ad", "in partnership with @X", etc.'
    )
    mentioned_tokens: list[dict[str, Any]] = Field(
        default_factory=list,
        description='Token mentions: [{"symbol":"TOKEN_A","sentiment":"bullish"}, ...]',
    )


class Tweet(BaseModel):
    """A single tweet with metrics and optional Phase 1d classification."""

    id: str
    created_at: Optional[str] = None  # ISO8601 string
    text: str = ""
    lang: Optional[str] = None
    referenced_tweets: list[ReferencedTweet] = Field(default_factory=list)
    public_metrics: PublicMetrics = Field(default_factory=PublicMetrics)

    # Classification (populated by Phase 1d; null until then)
    classification: Optional[PostClassification] = None

    @property
    def tweet_type(self) -> TweetTypeLiteral:
        """Classify from referenced_tweets. X API v2 doesn't provide this directly."""
        for ref in self.referenced_tweets:
            if ref.type == "retweeted":
                return "retweet"
            if ref.type == "replied_to":
                return "reply"
            if ref.type == "quoted":
                return "quote"
        return "original"

    @property
    def is_authored(self) -> bool:
        """True if this counts as the KOL's own broadcast content (original + quote).

        Used by EQR (§4.1). Empirical finding: restricting to pure originals
        excluded 32% of core-sample KOLs who express via quote-tweets. Including
        quote tweets recovers most of those.
        """
        return self.tweet_type in ("original", "quote")


# ============================================================
# Profile and contact
# ============================================================


class Profile(BaseModel):
    """User-level profile metadata."""

    followers: int = 0
    following: int = 0
    joined: Optional[str] = None  # "YYYY-MM" or ISO date
    verified: bool = False
    bio: str = ""
    is_dm_open: Optional[bool] = None
    # tier may be None for unclassified users (raw candidates, orgs). Sub-scores
    # that require tier (Response Likelihood) return null in that case.
    tier: Optional[TierLiteral] = None


class ContactSignals(BaseModel):
    """Contact channels parsed from bio / pinned tweet / external databases (Phase 1d)."""

    email_in_bio: Optional[str] = None
    telegram_handle: Optional[str] = None
    website: Optional[str] = None
    agent_contact: Optional[str] = None


class CooperabilityHardFilter(BaseModel):
    """v3 hard-filter output from Phase 1d classifier.

    KOLs with `is_contactable=False` or `accepts_paid_promos=False` are moved
    to `observe_only.json` and do NOT reach the scoring step. This model stores
    the filter decision for audit/display purposes.
    """

    is_contactable: bool
    accepts_paid_promos: bool
    contact_method: str
    public_email: Optional[str] = None
    public_telegram: Optional[str] = None


# ============================================================
# Aggregate stats used by scoring
# ============================================================


class PostsLast30d(BaseModel):
    """Aggregate counts over the KOL's last 30 days, used by Response Likelihood."""

    total_count: int = 0
    reply_count: int = 0  # replies the KOL made to others
    original_count: int = 0
    quote_count: int = 0


class ReplyStreamSample(BaseModel):
    """Sample of the last ~100 replies the KOL received on their own posts.

    Used by Audience Authenticity (§4.3) and by EQR's spam-reply adjustment (§4.1).
    Fetched in Phase 1d via `/tweets/search/recent` with `conversation_id` filter.
    """

    total_replies_sampled: int = 0
    unique_repliers: int = 0
    spam_flagged_count: int = 0


class PromoHistory90d(BaseModel):
    """Claude's scan of last 90 days for sponsor disclosure phrases.

    Feeds Layer 3 Promo History sub-score (§6.2).
    """

    promo_match_count: int = 0
    promo_examples: list[str] = Field(default_factory=list, max_length=5)


class PastRateDisclosures(BaseModel):
    """Rate card / pricing history used by Price Predictability sub-score (§6.4)."""

    has_public_rate_card: bool = False
    inferred_from_past_promos: bool = False
    rate_card_url: Optional[str] = None


class NetworkStats(BaseModel):
    """Phase 1c graph build output. Feeds Network Position sub-score (§4.5).

    Thresholds in scoring_spec.md §4.5 are calibrated on the current 66-core-node
    sample from `pipeline/circles/graph_v1.json` (2026-04-08).
    """

    t1_mutual_count: int = 0
    cross_cluster_mutual_count: int = 0
    bridge_ratio: float = Field(0.0, ge=0.0, le=1.0)
    cluster_id: Optional[int] = None


# ============================================================
# On-chain (optional; 15-20% coverage expected)
# ============================================================


class TokenHolding(BaseModel):
    symbol: str
    balance_usd: float
    chain: str = "ethereum"


class OnchainData(BaseModel):
    """On-chain data block. Feeds Layer 2 scores (§5).

    When `wallet_public` is False, the entire Layer 2 is skipped (onchain_score = null).
    Current Phase 2 bootstrap returns null for all KOLs until Etherscan/Arkham
    integration is built.
    """

    wallet_public: bool = False
    wallet_address: Optional[str] = None
    chain: str = "ethereum"
    holdings: list[TokenHolding] = Field(default_factory=list)
    protocols_used: list[str] = Field(default_factory=list)
    gov_votes: list[dict[str, Any]] = Field(default_factory=list)
    tx_count_30d: int = 0


# ============================================================
# Top-level input: KolRaw
# ============================================================


class KolRaw(BaseModel):
    """Normalized scoring input for ONE KOL.

    This is the single source of truth for what the three-layer scoring system
    consumes. See scoring/schema.md for the mapping from existing pipeline files
    (classified_kols.json, core_tweets.json, graph_v1.json) to this shape.

    Required fields: handle, profile.
    Everything else is optional — the scorer returns null sub-scores when data
    is missing, with confidence flags indicating why.
    """

    model_config = ConfigDict(extra="allow")  # tolerate extra fields from pipeline

    handle: str = Field(..., description="KOL Twitter/X handle without @ prefix")
    profile: Profile

    contact_signals: ContactSignals = Field(default_factory=ContactSignals)
    cooperability_hard_filter: Optional[CooperabilityHardFilter] = None

    recent_posts: list[Tweet] = Field(
        default_factory=list,
        description="Last 20 tweets (mix of original/retweet/quote/reply); EQR uses authored subset",
    )

    posts_last_30d: Optional[PostsLast30d] = None
    reply_stream_sample: Optional[ReplyStreamSample] = None
    network_stats: Optional[NetworkStats] = None
    promo_history_90d: Optional[PromoHistory90d] = None
    past_rate_disclosures: Optional[PastRateDisclosures] = None
    onchain: Optional[OnchainData] = None

    campaign_history: list[dict[str, Any]] = Field(
        default_factory=list, description="Historical campaigns for Campaign Impact Score (empty in bootstrap)"
    )

    @property
    def has_onchain(self) -> bool:
        return self.onchain is not None and self.onchain.wallet_public


# ============================================================
# Output: ScoreTrace + ScoredKol
# ============================================================


class ScoreTrace(BaseModel):
    """Trace object for ONE sub-score. Powers the 'See calculation' UI panel.

    Every scoring function returns a ScoreTrace even on failure — the `value`
    is null when uncomputable, and `notes` explains why.
    """

    value: Optional[float] = Field(None, description="0-100 sub-score, or null if uncomputable")
    formula: str = Field(..., description="Human-readable formula (for UI display)")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Raw values pulled from KolRaw")
    calculation: str = Field("", description="Substituted formula with actual numbers")
    confidence: ConfidenceLiteral
    notes: Optional[str] = None


class ScoredKol(BaseModel):
    """Output of `score_kol(kol_raw)`. Three parallel scores, never fused.

    IMPORTANT: There is no `overall_score` field. The UI, dashboard, and export
    layer must show Quality + Cooperability as two adjacent main-line scores.
    See scoring_spec.md §7 for the rationale.
    """

    handle: str

    # Three parallel top-line scores
    quality_score: Optional[float] = None
    cooperability_score: Optional[float] = None
    onchain_score: Optional[float] = None

    # Per-layer traces (for the "See calculation" UI)
    quality_trace: dict[str, ScoreTrace] = Field(default_factory=dict)
    cooperability_trace: dict[str, ScoreTrace] = Field(default_factory=dict)
    onchain_trace: Optional[dict[str, ScoreTrace]] = None

    # Layer confidence (min of sub-scores' confidence)
    quality_confidence: ConfidenceLiteral = "n/a"
    cooperability_confidence: ConfidenceLiteral = "n/a"
    onchain_confidence: ConfidenceLiteral = "n/a"

    # Version marker — if scoring spec changes, old ScoredKol records can be detected
    scored_with_version: str = "v3_2026-04-09"


# ============================================================
# Convenience loaders
# ============================================================


def tweet_from_x_api(raw: dict[str, Any]) -> Tweet:
    """Build a Tweet from a raw X API v2 `/users/:id/tweets` entry.

    The X API returns a dict with fields: id, text, created_at, lang,
    public_metrics, referenced_tweets. We normalize to the `Tweet` schema.
    """
    return Tweet.model_validate(
        {
            "id": raw.get("id", ""),
            "created_at": raw.get("created_at"),
            "text": raw.get("text", ""),
            "lang": raw.get("lang"),
            "referenced_tweets": raw.get("referenced_tweets", []) or [],
            "public_metrics": raw.get("public_metrics", {}),
        }
    )


def export_json_schema(indent: int = 2) -> str:
    """Export KolRaw + ScoredKol as JSON Schema (for React demo consumption)."""
    import json

    return json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "KOL Intelligence Engine Scoring Schema",
            "definitions": {
                "KolRaw": KolRaw.model_json_schema(),
                "ScoredKol": ScoredKol.model_json_schema(),
            },
        },
        indent=indent,
    )


if __name__ == "__main__":
    # CLI: python -m scoring.schema > scoring/kol_schema.json
    print(export_json_schema())
