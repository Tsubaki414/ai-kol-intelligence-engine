"""
Synthetic KolRaw fixtures for scoring unit tests.

Six cases covering the edge cases called out in scoring_spec.md §11:
  1. full_data_kol                — all L1+L3 sub-scores computable
  2. no_onchain_kol               — onchain null, L1+L3 full
  3. insufficient_engagement_kol  — EQR null, other L1 computable
  4. high_quality_non_commercial  — high Quality, low Cooperability
  5. high_coop_low_quality        — low Quality, high Cooperability
  6. insufficient_breadth         — only 1 sub-score per layer → null aggregate
"""

from __future__ import annotations

from scoring.schema import (
    ContactSignals,
    CooperabilityHardFilter,
    KolRaw,
    NetworkStats,
    PastRateDisclosures,
    PostClassification,
    PostsLast30d,
    Profile,
    PromoHistory90d,
    PublicMetrics,
    ReferencedTweet,
    ReplyStreamSample,
    Tweet,
)


def _make_tweet(
    tweet_id: str,
    *,
    content_class: str = "original_deep_analysis",
    is_ai_crypto: bool = True,
    sector: str = "AI Agent",
    originality_raw: int = 90,
    like: int = 500,
    reply: int = 100,
    rt: int = 50,
    quote: int = 30,
    tweet_kind: str = "original",  # "original" | "quote" | "retweet" | "reply"
    promo_match: str | None = None,
) -> Tweet:
    refs: list[ReferencedTweet] = []
    if tweet_kind == "retweet":
        refs = [ReferencedTweet(type="retweeted", id="ref1")]
    elif tweet_kind == "quote":
        refs = [ReferencedTweet(type="quoted", id="ref1")]
    elif tweet_kind == "reply":
        refs = [ReferencedTweet(type="replied_to", id="ref1")]

    return Tweet(
        id=tweet_id,
        text=f"sample text for {tweet_id}",
        referenced_tweets=refs,
        public_metrics=PublicMetrics(
            like_count=like, reply_count=reply, retweet_count=rt, quote_count=quote
        ),
        classification=PostClassification(
            content_class=content_class,  # type: ignore[arg-type]
            is_ai_generated_suspected=False,
            sector=sector,
            is_ai_crypto_related=is_ai_crypto,
            originality_score_raw=originality_raw,
            promo_match=promo_match,
        ),
    )


# ============================================================
# Fixture 1: full data, all sub-scores computable
# ============================================================


def full_data_kol() -> KolRaw:
    """Macro KOL with every data source populated.

    Expected: Quality ≈ high 70s-80s, Cooperability ≈ 60s, both "high" confidence.
    """
    tweets = [
        _make_tweet(f"t{i}", originality_raw=88, like=400, reply=80, rt=40, quote=20)
        for i in range(20)
    ]
    return KolRaw(
        handle="test_full",
        profile=Profile(
            followers=50000,
            following=1500,
            joined="2020-01",
            verified=True,
            bio="AI Agent researcher. Reach me at hi@test.com or telegram @test_tg.",
            is_dm_open=True,
            tier="Macro",
        ),
        contact_signals=ContactSignals(
            email_in_bio="hi@test.com",
            telegram_handle="@test_tg",
        ),
        cooperability_hard_filter=CooperabilityHardFilter(
            is_contactable=True,
            accepts_paid_promos=True,
            contact_method="email",
            public_email="hi@test.com",
            public_telegram="@test_tg",
        ),
        recent_posts=tweets,
        posts_last_30d=PostsLast30d(
            total_count=100, reply_count=35, original_count=60, quote_count=5
        ),
        reply_stream_sample=ReplyStreamSample(
            total_replies_sampled=100, unique_repliers=82, spam_flagged_count=4
        ),
        network_stats=NetworkStats(
            t1_mutual_count=7,
            cross_cluster_mutual_count=4,
            bridge_ratio=4 / 7,
            cluster_id=1,
        ),
        promo_history_90d=PromoHistory90d(
            promo_match_count=4,
            promo_examples=["#ad Project X", "in partnership with @Y"],
        ),
        past_rate_disclosures=PastRateDisclosures(
            has_public_rate_card=True,
            rate_card_url="https://test.com/rates",
        ),
    )


# ============================================================
# Fixture 2: no on-chain
# ============================================================


def no_onchain_kol() -> KolRaw:
    """Same as full_data_kol but no on-chain wallet. Layer 2 should be null."""
    kol = full_data_kol()
    kol.handle = "test_no_onchain"
    kol.onchain = None  # explicit (already None from fixture 1)
    return kol


# ============================================================
# Fixture 3: insufficient engagement (EQR null)
# ============================================================


def insufficient_engagement_kol() -> KolRaw:
    """Small account: < 100 cumulative casual interactions → EQR null.

    The other Layer 1 sub-scores (Originality, Sector, Network Position)
    still compute, so Quality renormalizes across them.
    """
    tweets = [
        _make_tweet(f"t{i}", like=3, reply=1, rt=1, quote=0, originality_raw=75)
        for i in range(20)
    ]  # Σcasual = 20*(3+1) = 80 < 100 threshold
    kol = full_data_kol()
    kol.handle = "test_insufficient_eng"
    kol.recent_posts = tweets
    return kol


# ============================================================
# Fixture 4: high quality, non-commercial (low cooperability)
# ============================================================


def high_quality_non_commercial_kol() -> KolRaw:
    """A brilliant builder-KOL: high content signal, zero promo history,
    no public contact, DMs closed. Quality 90+, Cooperability <30.
    """
    tweets = [
        _make_tweet(
            f"t{i}",
            content_class="original_deep_analysis",
            originality_raw=95,
            like=800,
            reply=200,
            rt=100,
            quote=50,
        )
        for i in range(20)
    ]
    return KolRaw(
        handle="test_builder",
        profile=Profile(
            followers=120000,
            following=200,
            joined="2018-03",
            verified=True,
            bio="I build things. Opinions my own. No DMs about promos.",
            is_dm_open=False,
            tier="Mega",
        ),
        contact_signals=ContactSignals(
            email_in_bio=None,
            telegram_handle=None,
            website="https://example.com",
        ),
        cooperability_hard_filter=CooperabilityHardFilter(
            is_contactable=False,
            accepts_paid_promos=False,
            contact_method="none_public",
        ),
        recent_posts=tweets,
        posts_last_30d=PostsLast30d(
            # Builder pattern: broadcasts originals, rarely replies to others.
            # reply_ratio = 3/60 = 0.05 < 0.10 → reply_freq_mult 0.75, bidir 0.90
            total_count=60, reply_count=3, original_count=57, quote_count=0
        ),
        reply_stream_sample=ReplyStreamSample(
            total_replies_sampled=100, unique_repliers=85, spam_flagged_count=3
        ),
        network_stats=NetworkStats(
            t1_mutual_count=6,
            cross_cluster_mutual_count=3,
            bridge_ratio=0.5,
            cluster_id=2,
        ),
        promo_history_90d=PromoHistory90d(promo_match_count=0, promo_examples=[]),
        past_rate_disclosures=PastRateDisclosures(
            has_public_rate_card=False, inferred_from_past_promos=False
        ),
    )


# ============================================================
# Fixture 5: high cooperability, low quality
# ============================================================


def high_coop_low_quality_kol() -> KolRaw:
    """Micro tier commercial account: email in bio, regular sponsor posts,
    weak original content. Quality <50, Cooperability 80+.
    """
    tweets = [
        _make_tweet(
            f"t{i}",
            content_class="meme_casual",
            originality_raw=30,
            is_ai_crypto=(i < 5),  # only 25% AI+Crypto
            like=120,
            reply=8,
            rt=25,
            quote=2,
            promo_match="#ad" if i < 6 else None,
        )
        for i in range(20)
    ]
    return KolRaw(
        handle="test_commercial",
        profile=Profile(
            followers=5000,
            following=1200,
            joined="2023-06",
            verified=False,
            bio="Crypto content creator. Business: promo@test.com | TG @test_promo",
            is_dm_open=True,
            tier="Micro",
        ),
        contact_signals=ContactSignals(
            email_in_bio="promo@test.com",
            telegram_handle="@test_promo",
        ),
        cooperability_hard_filter=CooperabilityHardFilter(
            is_contactable=True,
            accepts_paid_promos=True,
            contact_method="email",
            public_email="promo@test.com",
            public_telegram="@test_promo",
        ),
        recent_posts=tweets,
        posts_last_30d=PostsLast30d(
            total_count=80, reply_count=25, original_count=45, quote_count=10
        ),
        reply_stream_sample=ReplyStreamSample(
            total_replies_sampled=60, unique_repliers=40, spam_flagged_count=8
        ),
        network_stats=NetworkStats(
            t1_mutual_count=2,
            cross_cluster_mutual_count=1,
            bridge_ratio=0.5,
            cluster_id=0,
        ),
        promo_history_90d=PromoHistory90d(
            promo_match_count=6,
            promo_examples=["#ad A", "#ad B", "#ad C"],
        ),
        past_rate_disclosures=PastRateDisclosures(
            has_public_rate_card=False,
            inferred_from_past_promos=True,
        ),
    )


# ============================================================
# Fixture 6: insufficient breadth (only 1 sub-score per layer)
# ============================================================


def insufficient_breadth_kol() -> KolRaw:
    """Only Network Position (Layer 1) and Contact Accessibility (Layer 3) computable.

    Both aggregates should return null because MIN_SUB_SCORES_FOR_AGGREGATE = 2.
    """
    return KolRaw(
        handle="test_minimal",
        profile=Profile(
            followers=200,
            following=300,
            tier="Nano",
            bio="Contact: nano@test.com",
            is_dm_open=False,
        ),
        contact_signals=ContactSignals(email_in_bio="nano@test.com"),
        cooperability_hard_filter=CooperabilityHardFilter(
            is_contactable=True,
            accepts_paid_promos=True,
            contact_method="email",
        ),
        recent_posts=[],  # no tweets → EQR null, Originality null, Sector null
        network_stats=NetworkStats(
            t1_mutual_count=6,
            cross_cluster_mutual_count=6,
            bridge_ratio=1.0,
            cluster_id=0,
        ),
        # No Phase 1d data at all → Promo History null
        promo_history_90d=None,
        # No posts_last_30d → Response Likelihood falls back to defaults but still computes
        posts_last_30d=None,
    )


# ============================================================
# Registry for test parametrization
# ============================================================


ALL_FIXTURES = {
    "full_data": full_data_kol,
    "no_onchain": no_onchain_kol,
    "insufficient_engagement": insufficient_engagement_kol,
    "high_quality_non_commercial": high_quality_non_commercial_kol,
    "high_coop_low_quality": high_coop_low_quality_kol,
    "insufficient_breadth": insufficient_breadth_kol,
}
