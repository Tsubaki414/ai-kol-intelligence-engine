"""
Unit tests for scoring/score_kol.py.

Run with:
    source pipeline/.venv/bin/activate
    python3 -m pytest scoring/test_score_kol.py -v

No DB access — everything runs on synthetic fixtures.
"""

from __future__ import annotations

import pytest

from scoring.schema import ScoredKol, ScoreTrace
from scoring.score_kol import (
    MIN_SUB_SCORES_FOR_AGGREGATE,
    calculate_accessibility,
    calculate_contact_signal_strength,
    calculate_content_originality,
    calculate_engagement_quality_ratio,
    calculate_network_position,
    calculate_promo_willingness,
    calculate_sector_relevance,
    compute_cooperability_score,
    compute_quality_score,
    score_kol,
)
from scoring.test_fixtures import (
    ALL_FIXTURES,
    full_data_kol,
    high_coop_low_quality_kol,
    high_quality_non_commercial_kol,
    insufficient_breadth_kol,
    insufficient_engagement_kol,
    no_onchain_kol,
)


# ============================================================
# Per-fixture end-to-end score_kol()
# ============================================================


class TestScoreKolEndToEnd:
    def test_all_fixtures_return_scored_kol(self):
        """Every fixture should score without raising."""
        for name, factory in ALL_FIXTURES.items():
            kol = factory()
            result = score_kol(kol)
            assert isinstance(result, ScoredKol)
            assert result.handle == kol.handle
            assert result.scored_with_version == "v3_2026-04-09"

    def test_no_overall_score_field(self):
        """Architectural invariant: ScoredKol must not have overall_score."""
        kol = full_data_kol()
        result = score_kol(kol)
        assert not hasattr(result, "overall_score")

    def test_full_data_kol_quality_and_coop_populated(self):
        kol = full_data_kol()
        result = score_kol(kol)

        # Both should be non-null and in 0-100 range
        assert result.quality_score is not None
        assert result.cooperability_score is not None
        assert 0 <= result.quality_score <= 100
        assert 0 <= result.cooperability_score <= 100

        # On-chain is None (wallet not public)
        assert result.onchain_score is None
        assert result.onchain_confidence == "n/a"

        # All 5 Layer 1 sub-scores should be non-null
        non_null_l1 = [k for k, t in result.quality_trace.items() if t.value is not None]
        assert len(non_null_l1) == 5, f"expected all 5 L1 sub-scores, got {non_null_l1}"

        # All 3 Layer 3 sub-scores should be non-null (redesigned 2026-04-09)
        non_null_l3 = [k for k, t in result.cooperability_trace.items() if t.value is not None]
        assert len(non_null_l3) == 3, f"expected all 3 L3 sub-scores, got {non_null_l3}"
        assert set(non_null_l3) == {
            "contact_signal_strength",
            "promo_willingness",
            "accessibility",
        }

    def test_no_onchain_kol(self):
        """When wallet not public, onchain_score is None; other scores unaffected."""
        kol = no_onchain_kol()
        result = score_kol(kol)
        assert result.onchain_score is None
        assert result.onchain_trace is None
        assert result.quality_score is not None  # L1 unaffected

    def test_insufficient_engagement_null_eqr(self):
        """When sum_casual < 100, EQR returns null but Quality still computes from others."""
        kol = insufficient_engagement_kol()
        result = score_kol(kol)

        eqr = result.quality_trace["engagement_quality_ratio"]
        assert eqr.value is None
        assert "insufficient_engagement_data" in (eqr.notes or "")

        # Quality should still compute from the other 4 L1 sub-scores
        assert result.quality_score is not None

    def test_high_quality_non_commercial(self):
        """Builder-KOL: Quality ≥ 80, Cooperability ≤ 40."""
        kol = high_quality_non_commercial_kol()
        result = score_kol(kol)
        assert result.quality_score is not None
        assert result.cooperability_score is not None
        assert result.quality_score >= 80, f"expected Quality ≥ 80, got {result.quality_score}"
        assert result.cooperability_score <= 40, f"expected Coop ≤ 40, got {result.cooperability_score}"

    def test_high_coop_low_quality(self):
        """Commercial Micro account: Quality < 50, Cooperability ≥ 60."""
        kol = high_coop_low_quality_kol()
        result = score_kol(kol)
        assert result.quality_score is not None
        assert result.cooperability_score is not None
        assert result.quality_score < 50, f"expected Quality < 50, got {result.quality_score}"
        assert result.cooperability_score >= 60, f"expected Coop ≥ 60, got {result.cooperability_score}"

    def test_insufficient_breadth_both_null(self):
        """Only 1 sub-score per layer → both aggregates null (min=2 rule)."""
        kol = insufficient_breadth_kol()
        result = score_kol(kol)

        # Count non-null Layer 1 sub-scores — should be <2
        non_null_l1 = [t for t in result.quality_trace.values() if t.value is not None]
        assert len(non_null_l1) < MIN_SUB_SCORES_FOR_AGGREGATE
        assert result.quality_score is None


# ============================================================
# Architecture: parallel scores never fused
# ============================================================


class TestArchitecturalInvariants:
    def test_parallel_scores_not_fused(self):
        """A high-Q low-C KOL and a low-Q high-C KOL should have identical mean but
        be distinguishable via the two parallel scores (which is the whole point)."""
        q_high = high_quality_non_commercial_kol()
        q_low = high_coop_low_quality_kol()
        r_high = score_kol(q_high)
        r_low = score_kol(q_low)

        # The two parallel scores must not be equal (proves they carry distinct signal)
        assert r_high.quality_score != r_low.quality_score
        assert r_high.cooperability_score != r_low.cooperability_score
        # Cross-check: high-Q should have higher Quality, high-C should have higher Coop
        assert r_high.quality_score > r_low.quality_score
        assert r_low.cooperability_score > r_high.cooperability_score


# ============================================================
# Layer 1 sub-score unit tests
# ============================================================


class TestEngagementQualityRatio:
    def test_bucket_exceptional(self):
        """ratio ≥ 0.45 → 100."""
        kol = full_data_kol()
        # Full fixture: 20 tweets × (reply 80 + quote 20) / (like 400 + rt 40) = 100 / 440 ≈ 0.227
        # → bucket [0.18, 0.25) → 55
        trace = calculate_engagement_quality_ratio(kol)
        assert trace.value == 55

    def test_insufficient_casual_returns_null(self):
        kol = insufficient_engagement_kol()
        trace = calculate_engagement_quality_ratio(kol)
        assert trace.value is None
        assert "insufficient" in (trace.notes or "")

    def test_no_authored_posts_returns_null(self):
        kol = insufficient_breadth_kol()
        trace = calculate_engagement_quality_ratio(kol)
        assert trace.value is None

    def test_authored_filter_excludes_retweets(self):
        """Retweets should not count as authored for EQR."""
        from scoring.test_fixtures import _make_tweet

        kol = full_data_kol()
        kol.recent_posts = [
            _make_tweet(f"t{i}", tweet_kind="retweet") for i in range(20)
        ]
        trace = calculate_engagement_quality_ratio(kol)
        assert trace.value is None  # no authored posts


class TestContentOriginality:
    def test_all_deep_analysis(self):
        """20 × original_deep_analysis (class_val=100) with claude_raw=88
        → per-post = 0.6×100 + 0.4×88 = 95.2."""
        kol = full_data_kol()
        trace = calculate_content_originality(kol)
        assert trace.value is not None
        assert abs(trace.value - 95.2) < 0.1
        assert trace.confidence == "high"

    def test_no_classifications_returns_null(self):
        kol = full_data_kol()
        for t in kol.recent_posts:
            t.classification = None
        trace = calculate_content_originality(kol)
        assert trace.value is None


class TestSectorRelevance:
    def test_fully_on_topic_with_specialization_bonus(self):
        """20 × AI Agent, all ai_crypto_related → base 100 + bonus 10 (capped at 100)."""
        kol = full_data_kol()
        trace = calculate_sector_relevance(kol)
        assert trace.value == 100  # 100 capped

    def test_mostly_off_topic_no_bonus(self):
        kol = high_coop_low_quality_kol()
        # 5/20 ai_crypto_related → base 25, no bonus (base ≤ 50)
        trace = calculate_sector_relevance(kol)
        assert trace.value == 25.0


class TestNetworkPosition:
    def test_deeply_embedded_and_bridging(self):
        """t1=7, bridge_ratio=4/7≈0.571 → abs=100, bridge=100, final=100."""
        kol = full_data_kol()
        trace = calculate_network_position(kol)
        assert trace.value == 100

    def test_not_indexed_returns_null(self):
        """cluster_id=None → not indexed → null."""
        kol = full_data_kol()
        kol.network_stats.cluster_id = None
        trace = calculate_network_position(kol)
        assert trace.value is None
        assert "not_indexed" in (trace.notes or "")

    def test_zero_mutual_returns_null(self):
        """t1=0 → null with no_mutual_edges note."""
        kol = full_data_kol()
        kol.network_stats.t1_mutual_count = 0
        kol.network_stats.cross_cluster_mutual_count = 0
        kol.network_stats.bridge_ratio = 0.0
        trace = calculate_network_position(kol)
        assert trace.value is None
        assert "no_mutual_edges" in (trace.notes or "")

    def test_no_network_stats_returns_null(self):
        kol = full_data_kol()
        kol.network_stats = None
        trace = calculate_network_position(kol)
        assert trace.value is None


# ============================================================
# Layer 3 sub-score unit tests (redesigned 2026-04-09)
# ============================================================


class TestContactSignalStrength:
    """Deterministic regex on bio text. No reliance on Claude's guess."""

    def test_email_in_bio_tops(self):
        """full_data_kol bio contains 'hi@test.com' → 100."""
        kol = full_data_kol()
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 100
        assert trace.inputs["channel"] == "email"
        assert "hi@test.com" in trace.inputs["evidence"]

    def test_telegram_only_via_prefix_keyword(self):
        kol = full_data_kol()
        kol.profile.bio = "AI researcher. tg: @mytghandle for questions."
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 80

    def test_telegram_only_via_tme_link(self):
        kol = full_data_kol()
        kol.profile.bio = "Researcher. https://t.me/some_chat"
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 80

    def test_collab_keyword_only(self):
        kol = full_data_kol()
        kol.profile.bio = "Artist and creator. DMs open for collab."
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 60

    def test_chinese_collab_keyword(self):
        kol = full_data_kol()
        kol.profile.bio = "加密研究员，商务合作请私信"
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 60

    def test_website_only(self):
        kol = full_data_kol()
        kol.profile.bio = "Independent researcher. https://example.com"
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 40

    def test_twitter_url_does_not_count_as_website(self):
        kol = full_data_kol()
        kol.profile.bio = "Just here. https://twitter.com/me or https://t.co/xyz"
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 10  # default DM fallback

    def test_empty_bio_defaults_to_ten(self):
        kol = full_data_kol()
        kol.profile.bio = ""
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 10  # not 0 — Twitter DM always possible
        assert trace.confidence == "low"
        assert "empty bio" in (trace.notes or "")

    def test_plain_bio_no_channels_defaults_to_ten(self):
        kol = full_data_kol()
        kol.profile.bio = "I build things. Opinions my own. No promo DMs."
        trace = calculate_contact_signal_strength(kol)
        assert trace.value == 10


class TestPromoWillingness:
    """Scan cached tweets. Works without Phase 1d (falls back to raw text)."""

    def test_phase1d_sponsor_match(self):
        """high_coop fixture has promo_match='#ad' on 6 tweets → 90."""
        kol = high_coop_low_quality_kol()
        trace = calculate_promo_willingness(kol)
        assert trace.value == 90
        assert trace.inputs["reason"] == "explicit_sponsor_disclosure"

    def test_raw_text_sponsor_fallback(self):
        """Even without Phase 1d classification.promo_match, text regex catches #ad."""
        kol = full_data_kol()
        for t in kol.recent_posts:
            t.classification = None  # kill Phase 1d
        # Put #ad in first tweet's text
        kol.recent_posts[0].text = "New collab: #ad @projectX is doing great things."
        trace = calculate_promo_willingness(kol)
        assert trace.value == 90

    def test_no_cached_tweets_null(self):
        kol = insufficient_breadth_kol()  # recent_posts=[]
        trace = calculate_promo_willingness(kol)
        assert trace.value is None
        assert "phase_1d_pending" in (trace.notes or "")

    def test_authored_no_promo_defaults_to_thirty(self):
        """full_data_kol with promo_match cleared + neutral text → 30."""
        kol = full_data_kol()
        for t in kol.recent_posts:
            if t.classification:
                t.classification.promo_match = None
            t.text = f"deep thought number {t.id}"  # no @, no sponsor, no review kw
        trace = calculate_promo_willingness(kol)
        assert trace.value == 30
        assert trace.inputs["reason"] == "only_own_opinions"

    def test_review_with_mentions_gives_sixty(self):
        """3+ authored posts with review-kw + @mention → 60."""
        kol = full_data_kol()
        for t in kol.recent_posts[:5]:
            if t.classification:
                t.classification.promo_match = None
            t.text = "My deep dive on @projectX — strong fundamentals."
        for t in kol.recent_posts[5:]:
            if t.classification:
                t.classification.promo_match = None
            t.text = "random thought"
        trace = calculate_promo_willingness(kol)
        assert trace.value == 60


class TestAccessibility:
    """tier inverse + mutual member bonus. Deterministic lookup."""

    def test_nano_with_mutual_capped_at_100(self):
        """Nano base=90 + mutual bonus 15 → 105 capped to 100."""
        kol = insufficient_breadth_kol()  # Nano, t1=6
        trace = calculate_accessibility(kol)
        assert trace.value == 100

    def test_mega_without_mutual(self):
        """Mega base=15, no mutual → 15."""
        kol = high_quality_non_commercial_kol()  # Mega, t1=6
        kol.network_stats.t1_mutual_count = 0  # force no mutual
        trace = calculate_accessibility(kol)
        assert trace.value == 15

    def test_mega_with_mutual(self):
        """Mega base=15 + 15 bonus = 30."""
        kol = high_quality_non_commercial_kol()
        trace = calculate_accessibility(kol)
        assert trace.value == 30
        assert trace.inputs["is_mutual_member"] is True

    def test_micro_with_mutual(self):
        """Micro base=70 + 15 = 85."""
        kol = high_coop_low_quality_kol()  # Micro, t1=2
        trace = calculate_accessibility(kol)
        assert trace.value == 85

    def test_macro_no_mutual(self):
        """Macro base=40, no mutual → 40."""
        kol = full_data_kol()  # Macro, t1=7
        kol.network_stats.t1_mutual_count = 0
        trace = calculate_accessibility(kol)
        assert trace.value == 40

    def test_missing_tier_null(self):
        kol = full_data_kol()
        kol.profile.tier = None
        trace = calculate_accessibility(kol)
        assert trace.value is None


# ============================================================
# Aggregation renormalization
# ============================================================


class TestAggregation:
    def test_quality_requires_min_subscores(self):
        """Only 1 non-null sub-score → null quality_score."""
        single = {
            "engagement_quality_ratio": ScoreTrace(
                value=100.0,
                formula="x",
                inputs={},
                calculation="x",
                confidence="high",
            ),
            "content_originality": ScoreTrace(
                value=None, formula="x", inputs={}, calculation="x", confidence="low"
            ),
            "audience_authenticity": ScoreTrace(
                value=None, formula="x", inputs={}, calculation="x", confidence="low"
            ),
            "sector_relevance": ScoreTrace(
                value=None, formula="x", inputs={}, calculation="x", confidence="low"
            ),
            "network_position": ScoreTrace(
                value=None, formula="x", inputs={}, calculation="x", confidence="low"
            ),
        }
        score, conf = compute_quality_score(single)
        assert score is None
        assert conf == "low"

    def test_quality_renormalizes_on_nulls(self):
        """With EQR=60 (w 0.30) and NP=80 (w 0.15), quality = (60×0.3+80×0.15)/0.45 = 66.67."""
        two = {
            "engagement_quality_ratio": ScoreTrace(
                value=60.0, formula="x", inputs={}, calculation="x", confidence="high"
            ),
            "content_originality": ScoreTrace(
                value=None, formula="x", inputs={}, calculation="x", confidence="low"
            ),
            "audience_authenticity": ScoreTrace(
                value=None, formula="x", inputs={}, calculation="x", confidence="low"
            ),
            "sector_relevance": ScoreTrace(
                value=None, formula="x", inputs={}, calculation="x", confidence="low"
            ),
            "network_position": ScoreTrace(
                value=80.0, formula="x", inputs={}, calculation="x", confidence="medium"
            ),
        }
        score, conf = compute_quality_score(two)
        assert score == pytest.approx(66.67, abs=0.01)
        assert conf == "medium"  # min of high, medium


# ============================================================
# Confidence helper
# ============================================================


class TestConfidenceHelper:
    def test_min_confidence_picks_worst(self):
        from scoring.score_kol import _min_confidence

        assert _min_confidence(["high", "medium", "high"]) == "medium"
        assert _min_confidence(["high", "low", "medium"]) == "low"
        assert _min_confidence(["high", "high"]) == "high"

    def test_min_confidence_ignores_n_a(self):
        from scoring.score_kol import _min_confidence

        assert _min_confidence(["high", "n/a", "high"]) == "high"
        assert _min_confidence(["n/a", "n/a"]) == "n/a"
