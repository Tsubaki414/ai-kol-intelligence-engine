"""
Three-layer scoring orchestrator + sub-score functions.

See scoring/scoring_spec.md (v3 2026-04-09) for formulas, rationale, and
worked examples. This module is the executable counterpart — each scoring
function corresponds 1:1 with a spec section.

Layer 1 (Social Quality, 0-100):
    - engagement_quality_ratio  §4.1  weight 30%
    - content_originality       §4.2  weight 25%   (Phase 1d-dependent)
    - audience_authenticity     §4.3  weight 15%   (Phase 1d-dependent)
    - sector_relevance          §4.4  weight 15%   (Phase 1d-dependent)
    - network_position          §4.5  weight 15%

Layer 2 (On-chain, independent display, 0-100):
    - wallet_content_alignment  §5.1  (null in bootstrap)
    - onchain_activity_depth    §5.2  (null in bootstrap)
    - campaign_impact_score     §5.3  (null in bootstrap)

Layer 3 (Cooperability, 0-100):
    - contact_accessibility     §6.1  weight 30%
    - promo_history             §6.2  weight 30%   (Phase 1d-dependent)
    - response_likelihood       §6.3  weight 20%
    - price_predictability      §6.4  weight 20%

Output: ScoredKol with three PARALLEL scores (quality / cooperability / onchain).
No fusion, no overall_score. See spec §7.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from scoring.schema import (
    ConfidenceLiteral,
    KolRaw,
    ScoredKol,
    ScoreTrace,
)

# ============================================================
# Layer 1 sub-scores
# ============================================================

LAYER_1_WEIGHTS: dict[str, float] = {
    "engagement_quality_ratio": 0.30,
    "content_originality":      0.25,
    "audience_authenticity":    0.15,
    "sector_relevance":         0.15,
    "network_position":         0.15,
}


def calculate_engagement_quality_ratio(kol: KolRaw) -> ScoreTrace:
    """§4.1 — EQR = (replies + quotes) / (likes + retweets) over last 20 authored posts.

    Authored = original + quote (excludes retweets and pure replies).
    Bucket thresholds calibrated 2026-04-09 on 66-core sample. See
    pipeline/eqr_distribution.json.
    """
    authored = [t for t in kol.recent_posts if t.is_authored][:20]
    if not authored:
        return ScoreTrace(
            value=None,
            formula="(Σ reply + Σ quote) / (Σ like + Σ retweet) → bucket",
            inputs={"authored_count": 0},
            calculation="No authored posts in recent sample",
            confidence="low",
            notes="insufficient_data: 0 authored posts",
        )

    sum_replies = sum(t.public_metrics.reply_count for t in authored)
    sum_quotes = sum(t.public_metrics.quote_count for t in authored)
    sum_likes = sum(t.public_metrics.like_count for t in authored)
    sum_retweets = sum(t.public_metrics.retweet_count for t in authored)
    sum_depth = sum_replies + sum_quotes
    sum_casual = sum_likes + sum_retweets

    if sum_casual < 100:
        return ScoreTrace(
            value=None,
            formula="(Σ reply + Σ quote) / (Σ like + Σ retweet) → bucket",
            inputs={
                "authored_count": len(authored),
                "sum_depth": sum_depth,
                "sum_casual": sum_casual,
            },
            calculation=f"sum_casual = {sum_casual} < 100 threshold",
            confidence="low",
            notes="insufficient_engagement_data: cumulative casual interactions < 100",
        )

    # Spam-reply adjustment (only when reply_stream_sample is available).
    confidence: ConfidenceLiteral
    notes: str | None
    adjusted_depth: float
    if kol.reply_stream_sample and kol.reply_stream_sample.total_replies_sampled > 0:
        spam_fraction = min(
            kol.reply_stream_sample.spam_flagged_count
            / kol.reply_stream_sample.total_replies_sampled,
            0.30,
        )
        adjusted_depth = sum_depth * (1 - spam_fraction)
        confidence = "high" if len(authored) >= 10 else "medium"
        notes = None if spam_fraction == 0 else f"spam adjustment -{spam_fraction:.2%}"
    else:
        adjusted_depth = float(sum_depth)
        confidence = "medium"
        notes = "reply_stream_sample unavailable; spam adjustment skipped"

    raw_ratio = adjusted_depth / sum_casual

    # Bucket mapping (calibrated against P10/P25/P50/P75/P90 of real distribution)
    if raw_ratio >= 0.45:
        score = 100
    elif raw_ratio >= 0.35:
        score = 85
    elif raw_ratio >= 0.25:
        score = 70
    elif raw_ratio >= 0.18:
        score = 55
    elif raw_ratio >= 0.10:
        score = 40
    elif raw_ratio >= 0.05:
        score = 25
    else:
        score = 10

    return ScoreTrace(
        value=float(score),
        formula="(Σ replies + Σ quotes) / (Σ likes + Σ retweets) → bucket (calibrated 2026-04-09)",
        inputs={
            "authored_count": len(authored),
            "sum_replies": sum_replies,
            "sum_quotes": sum_quotes,
            "sum_likes": sum_likes,
            "sum_retweets": sum_retweets,
            "sum_depth": sum_depth,
            "sum_casual": sum_casual,
            "adjusted_depth": round(adjusted_depth, 2),
            "raw_ratio": round(raw_ratio, 4),
        },
        calculation=(
            f"depth = {sum_replies} + {sum_quotes} = {sum_depth}; "
            f"casual = {sum_likes} + {sum_retweets} = {sum_casual}; "
            f"ratio = {adjusted_depth:.1f} / {sum_casual} = {raw_ratio:.4f} → bucket score {score}"
        ),
        confidence=confidence,
        notes=notes,
    )


def calculate_network_position(kol: KolRaw) -> ScoreTrace:
    """§4.5 — Network Position = 0.5 × (absolute t1_mutual bucket) + 0.5 × (bridge_ratio bucket).

    Thresholds calibrated 2026-04-08 on 66-core sample (graph_v1.json).

    Returns null when:
      - network_stats wasn't derived (no data at all)
      - cluster_id is None (KOL not indexed in graph_v1 — anchor/hub/peripheral)
      - t1_mutual_count == 0 (in graph but not in the mutual subgraph — e.g. peripheral
        connected only via one-way follows)

    Rationale: scoring "t1=0" as literal 0 pollutes Quality Score for the majority
    of KOLs who simply haven't been indexed deeply enough yet. Null is more honest —
    Layer 1 renormalization drops the weight instead of zeroing the score.
    """
    ns = kol.network_stats
    if ns is None:
        return ScoreTrace(
            value=None,
            formula="0.5 × abs_bucket(t1_count) + 0.5 × bridge_bucket(bridge_ratio)",
            inputs={},
            calculation="network_stats not provided by loader",
            confidence="low",
            notes="not yet indexed in network graph",
        )

    t1 = ns.t1_mutual_count

    if ns.cluster_id is None:
        return ScoreTrace(
            value=None,
            formula="0.5 × abs_bucket(t1_count) + 0.5 × bridge_bucket(bridge_ratio)",
            inputs={"t1_mutual_count": t1, "cluster_id": None},
            calculation="cluster_id not set — KOL not present in graph_v1 node list",
            confidence="low",
            notes="not_indexed: KOL is not in the current network graph (no cluster assignment)",
        )

    if t1 == 0:
        return ScoreTrace(
            value=None,
            formula="0.5 × abs_bucket(t1_count) + 0.5 × bridge_bucket(bridge_ratio)",
            inputs={"t1_mutual_count": 0, "cluster_id": ns.cluster_id},
            calculation="KOL is in graph but has zero T1 mutual follows",
            confidence="low",
            notes="no_mutual_edges: in graph but only one-way follows (peripheral pattern); recalibrate after Phase 1b expansion",
        )

    # Absolute sub-score (calibrated on 66-core sample)
    if t1 >= 6:
        abs_score = 100
    elif t1 >= 3:
        abs_score = 60
    else:  # t1 in {1, 2}
        abs_score = 30

    # Bridge sub-score
    if ns.bridge_ratio >= 0.50:
        bridge_score = 100
    elif ns.bridge_ratio >= 0.30:
        bridge_score = 70
    elif ns.bridge_ratio >= 0.10:
        bridge_score = 40
    elif ns.bridge_ratio > 0:
        bridge_score = 20
    else:
        bridge_score = 0

    final = 0.5 * abs_score + 0.5 * bridge_score

    return ScoreTrace(
        value=round(final, 2),
        formula="0.5 × absolute_bucket(t1_mutual) + 0.5 × bridge_bucket(cross_cluster / t1_mutual)",
        inputs={
            "t1_mutual_count": t1,
            "cross_cluster_mutual_count": ns.cross_cluster_mutual_count,
            "bridge_ratio": round(ns.bridge_ratio, 4),
            "cluster_id": ns.cluster_id,
        },
        calculation=(
            f"absolute: t1={t1} → {abs_score}; "
            f"bridge: ratio={ns.bridge_ratio:.3f} → {bridge_score}; "
            f"final = 0.5×{abs_score} + 0.5×{bridge_score} = {final}"
        ),
        confidence="medium",
        notes="calibrated on 66-core sample 2026-04-08; recalibrate after Phase 1b graph expansion",
    )


ORIGINALITY_CLASS_VALUES: dict[str, int] = {
    "retweet": 0,
    "news_share": 20,
    "meme_casual": 40,
    "quote_with_commentary": 65,
    "original_observation": 80,
    "thread": 95,
    "original_deep_analysis": 100,
    "ai_generated_suspected": 15,
}


def calculate_content_originality(kol: KolRaw) -> ScoreTrace:
    """§4.2 — mean(0.6 × class_value + 0.4 × claude_raw_score) over classified posts."""
    classified = [t for t in kol.recent_posts if t.classification is not None][:20]
    if len(classified) < 5:
        return ScoreTrace(
            value=None,
            formula="mean(0.6 × class_value + 0.4 × claude_raw) over classified posts",
            inputs={"classified_count": len(classified)},
            calculation="Phase 1d Claude pre-classification not yet run (need ≥5 classified)",
            confidence="low",
            notes="phase_1d_pending or insufficient classified posts",
        )

    per_post_values: list[float] = []
    class_breakdown: dict[str, int] = {}
    for t in classified:
        c = t.classification
        if c is None:
            continue
        class_val = ORIGINALITY_CLASS_VALUES.get(c.content_class, 40)
        claude_raw = c.originality_score_raw
        post_val = 0.6 * class_val + 0.4 * claude_raw
        per_post_values.append(post_val)
        class_breakdown[c.content_class] = class_breakdown.get(c.content_class, 0) + 1

    score = sum(per_post_values) / len(per_post_values)

    return ScoreTrace(
        value=round(score, 2),
        formula="mean(0.6 × class_value + 0.4 × claude_raw_score) over last 20 classified posts",
        inputs={
            "classified_count": len(classified),
            "class_breakdown": class_breakdown,
            "mean_per_post": round(score, 2),
        },
        calculation=f"mean of {len(per_post_values)} per-post values = {score:.2f}",
        confidence="high" if len(classified) >= 10 else "medium",
        notes=None,
    )


def calculate_audience_authenticity(kol: KolRaw) -> ScoreTrace:
    """§4.3 — unique_repliers / total_replies_sampled bucketed to 0-100.

    Low unique_ratio indicates reply brigading / engagement farming (a small
    group of accounts coordinates to inflate engagement). High ratio = diverse
    organic audience.
    """
    rs = kol.reply_stream_sample
    if rs is None or rs.total_replies_sampled < 20:
        return ScoreTrace(
            value=None,
            formula="unique_repliers / total_replies_sampled → bucket",
            inputs={"total_replies_sampled": rs.total_replies_sampled if rs else 0},
            calculation="reply_stream_sample unavailable or < 20 replies",
            confidence="low",
            notes="phase_1d_pending: reply stream sample insufficient",
        )

    unique_ratio = rs.unique_repliers / rs.total_replies_sampled

    if unique_ratio >= 0.75:
        score = 95
    elif unique_ratio >= 0.60:
        score = 80
    elif unique_ratio >= 0.45:
        score = 60
    elif unique_ratio >= 0.30:
        score = 40
    elif unique_ratio >= 0.15:
        score = 20
    else:
        score = 5

    # Confidence scales with sample size
    if rs.total_replies_sampled >= 100:
        conf: ConfidenceLiteral = "high"
    elif rs.total_replies_sampled >= 50:
        conf = "medium"
    else:
        conf = "low"

    return ScoreTrace(
        value=float(score),
        formula="unique_repliers / total_replies_sampled → bucket",
        inputs={
            "total_replies_sampled": rs.total_replies_sampled,
            "unique_repliers": rs.unique_repliers,
            "spam_flagged_count": rs.spam_flagged_count,
            "unique_ratio": round(unique_ratio, 4),
        },
        calculation=f"{rs.unique_repliers} / {rs.total_replies_sampled} = {unique_ratio:.4f} → bucket score {score}",
        confidence=conf,
        notes=None,
    )


def calculate_sector_relevance(kol: KolRaw) -> ScoreTrace:
    """§4.4 — base = % ai_crypto_related posts, + specialization bonus if specialized."""
    classified = [t for t in kol.recent_posts if t.classification is not None][:20]
    if len(classified) < 5:
        return ScoreTrace(
            value=None,
            formula="(% ai_crypto_related) + specialization_bonus",
            inputs={"classified_count": len(classified)},
            calculation="Need ≥5 classified posts",
            confidence="low",
            notes="phase_1d_pending or insufficient classified posts",
        )

    total = len(classified)
    ai_crypto_count = sum(1 for t in classified if t.classification and t.classification.is_ai_crypto_related)
    base = (ai_crypto_count / total) * 100

    # Specialization bonus: top sector's concentration
    from collections import Counter

    sector_counts = Counter(
        t.classification.sector
        for t in classified
        if t.classification and t.classification.is_ai_crypto_related
    )
    specialization_bonus = 0.0
    top_sector = None
    top_share = 0.0
    if sector_counts:
        top_sector, top_count = sector_counts.most_common(1)[0]
        top_share = top_count / total
        specialization_bonus = min(10.0, top_share * 10)

    if base > 50:
        score = min(100.0, base + specialization_bonus)
        applied_bonus = specialization_bonus
    else:
        score = base
        applied_bonus = 0.0

    return ScoreTrace(
        value=round(score, 2),
        formula="(ai_crypto_related / total × 100) + specialization_bonus (max +10 when base > 50)",
        inputs={
            "classified_count": total,
            "ai_crypto_related_count": ai_crypto_count,
            "base_relevance": round(base, 2),
            "top_sector": top_sector,
            "top_sector_share": round(top_share, 3),
            "applied_bonus": round(applied_bonus, 2),
        },
        calculation=f"base={base:.1f} ({ai_crypto_count}/{total}) + bonus={applied_bonus:.1f} → {score:.2f}",
        confidence="high" if total >= 10 else "medium",
        notes=None,
    )


# ============================================================
# Layer 1 aggregation
# ============================================================


# Minimum non-null sub-score count for Layer 1 / Layer 3 aggregation.
# Prevents "false 100" or "false 0" from single-dimension renormalization.
# When only one sub-score is computable, we return null with "insufficient_breadth".
MIN_SUB_SCORES_FOR_AGGREGATE = 2


def compute_quality_score(traces: dict[str, ScoreTrace]) -> tuple[float | None, ConfidenceLiteral]:
    """Compute weighted Layer 1 score over AVAILABLE sub-scores only.

    Requires at least MIN_SUB_SCORES_FOR_AGGREGATE non-null sub-scores to avoid
    single-dimension renormalization producing misleading scores. If only one
    sub-score is computable, returns null — scoring on a single signal is noise.

    If ≥ 2 are computable, Layer 1 internal renormalization proportionally
    redistributes weight from null sub-scores across the available ones.
    """
    available = [(k, t.value) for k, t in traces.items() if t.value is not None]
    if len(available) < MIN_SUB_SCORES_FOR_AGGREGATE:
        return None, "low"

    total_w = sum(LAYER_1_WEIGHTS[k] for k, _ in available)
    weighted_sum = sum(LAYER_1_WEIGHTS[k] * v for k, v in available)
    score = round(weighted_sum / total_w, 2)

    # Confidence = minimum confidence across non-null sub-scores
    confs = [traces[k].confidence for k, _ in available]
    conf: ConfidenceLiteral = _min_confidence(confs)
    return score, conf


# ============================================================
# Layer 2 sub-scores (all return null in bootstrap)
# ============================================================


def calculate_wallet_content_alignment(kol: KolRaw) -> ScoreTrace:
    return _null_layer2("wallet_content_alignment", kol)


def calculate_onchain_activity_depth(kol: KolRaw) -> ScoreTrace:
    return _null_layer2("onchain_activity_depth", kol)


def calculate_campaign_impact_score(kol: KolRaw) -> ScoreTrace:
    return _null_layer2("campaign_impact_score", kol)


def _null_layer2(name: str, kol: KolRaw) -> ScoreTrace:
    if not kol.has_onchain:
        return ScoreTrace(
            value=None,
            formula=f"Layer 2 {name} (deferred)",
            inputs={"wallet_public": False},
            calculation="wallet not public; Layer 2 skipped entirely for this KOL",
            confidence="n/a",
            notes="wallet_not_public",
        )
    return ScoreTrace(
        value=None,
        formula=f"Layer 2 {name} (deferred)",
        inputs={},
        calculation="Etherscan/Arkham integration not yet built (bootstrap)",
        confidence="low",
        notes="layer_2_integration_pending",
    )


def compute_onchain_score(
    traces: dict[str, ScoreTrace], wallet_public: bool
) -> tuple[float | None, ConfidenceLiteral]:
    if not wallet_public:
        return None, "n/a"
    available = [(k, t.value) for k, t in traces.items() if t.value is not None]
    if not available:
        return None, "low"
    # Layer 2 weights (see spec §5.4)
    weights = {
        "wallet_content_alignment": 0.50,
        "onchain_activity_depth": 0.25,
        "campaign_impact_score": 0.25,
    }
    total_w = sum(weights[k] for k, _ in available)
    weighted_sum = sum(weights[k] * v for k, v in available)
    return round(weighted_sum / total_w, 2), _min_confidence(
        [traces[k].confidence for k, _ in available]
    )


# ============================================================
# Layer 3 — Cooperability (REDESIGNED 2026-04-09)
# ============================================================
#
# Supersedes old 4-dimension Layer 3 (contact_accessibility / promo_history /
# response_likelihood / price_predictability). The old design relied on
# Claude-guessed `cooperability_hard_filter.contact_method` (same hallucination
# source that polluted classified_kols.json pre-cleanup) and required Phase 1d
# data that was only run on 50/680 KOLs → compressed score distribution to
# 12-66 range for everyone, providing no signal.
#
# New design (3 dimensions):
#   - Contact Signal Strength (40%) — deterministic regex on bio text
#   - Promo Willingness       (30%) — scan cached tweets for sponsor/review
#   - Accessibility           (30%) — tier inverse + mutual member bonus
#
# Key property: each dimension derives from a concrete, inspectable signal
# that Dov can audit ("this score is 100 because this email appears in the
# bio") rather than "Claude said so".
# ============================================================

LAYER_3_WEIGHTS: dict[str, float] = {
    "contact_signal_strength": 0.40,
    "promo_willingness":       0.30,
    "accessibility":           0.30,
}

# ---- Bio regex patterns for Contact Signal Strength ----

_BIO_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Telegram: link, or "tg"/"telegram" followed by a handle (colon optional).
# Also matches Chinese patterns like "tg群", "加入tg群", "TG @handle".
_BIO_TELEGRAM_PATTERNS = [
    # t.me link (most reliable)
    re.compile(r"t\.me/[A-Za-z0-9_]{4,}", re.IGNORECASE),
    # "telegram: @handle" or "telegram @handle"
    re.compile(r"\btelegram\s*[:：@]?\s*@?[A-Za-z0-9_]{4,}", re.IGNORECASE),
    # "tg: handle" or "tg handle" or "TG handle123"
    re.compile(r"\btg\s*[:：]?\s*@?[A-Za-z0-9_]{4,}", re.IGNORECASE),
    # "tg群" (Chinese: telegram group) — weaker signal but consistent intent
    re.compile(r"tg群", re.IGNORECASE),
    re.compile(r"电报群|電報群"),
]

# Collab / partnership intent keywords (English + 中文).
# Includes "DM" (standalone) and "私信" since Chinese KOLs frequently say 请私信.
_BIO_COLLAB_KEYWORDS = re.compile(
    r"\bDMs?\s+open\b|"
    r"\bopen\s+to\s+(collabs?|dms?|partnerships?)\b|"
    r"\bcollab(oration)?s?\b|"
    r"\bpartnerships?\b|"
    r"\bbiz(ness)?\s+inquir(y|ies)\b|"
    r"\bfor\s+(promo|collab|inquiries)\b|"
    r"\bpromo\s+inquir(y|ies)\b|"
    r"\balways\s+hiring\b|"           # e.g. "Always hiring 永远招聘优秀人才可以DM"
    r"\bDM\s+(me|us|for|about)\b|"    # "DM me"
    r"\bHiring\b|"
    r"(商务|商业|商業|商務|"                     # 商务 = business
    r"商务合作|商業合作|业务合作|优质合作|"       # biz collab variants
    r"欢迎私信|歡迎私信|请私信|請私信|"          # "please DM"
    r"可以DM|可DM|免费加群请私信|"                 # "can DM / free to DM"
    r"私信我|私信X|私信 X|私信Ｘ|"               # "DM me / DM X"
    r"进群|加群|入群|"                            # join group (explicit verb)
    r"欢迎交流|歡迎交流|欢迎友好交流)",            # "welcome to chat"
    re.IGNORECASE,
)

_BIO_URL = re.compile(r"https?://\S+", re.IGNORECASE)
# Twitter-owned domains don't count as "personal website".
# t.co is X's URL shortener — every URL in bio is auto-wrapped in t.co on display,
# so we CANNOT distinguish "personal website" from "exchange affiliate link" just
# from bio text. Most crypto KOL t.co links are in fact affiliate links (Binance,
# OKX, Bitget referrals), so excluding t.co is the safer default.
_TWITTER_DOMAINS = ("twitter.com/", "x.com/", "mobile.twitter", "mobile.x", "t.co/")


def calculate_contact_signal_strength(kol: KolRaw) -> ScoreTrace:
    """Layer 3.1 (redesigned 2026-04-09) — deterministic bio regex matching.

    Replaces `calculate_contact_accessibility`, which read Claude's bio-parse
    guess. This version does its own regex match at scoring time, so the
    "evidence" for the score is always a literal substring of the bio.

    Tiered scoring (highest match wins):
      email in bio                                 → 100
      telegram handle in bio                       →  80
      "DMs open" / "collab" / "partnership" kw     →  60
      personal website URL                         →  40
      none of the above                            →  10
        (not 0 — Twitter DM is always a fallback channel)
    """
    bio = kol.profile.bio or ""

    email_match = _BIO_EMAIL.search(bio)

    tg_match = None
    for pattern in _BIO_TELEGRAM_PATTERNS:
        m = pattern.search(bio)
        if m:
            tg_match = m.group(0)
            break

    collab_match = _BIO_COLLAB_KEYWORDS.search(bio)

    website_match: str | None = None
    for url in _BIO_URL.findall(bio):
        if not any(dom in url.lower() for dom in _TWITTER_DOMAINS):
            website_match = url
            break

    if email_match:
        score, channel, evidence = 100, "email", email_match.group(0)
    elif tg_match:
        score, channel, evidence = 80, "telegram", tg_match
    elif collab_match:
        score, channel, evidence = 60, "collab_keyword", collab_match.group(0)
    elif website_match:
        score, channel, evidence = 40, "personal_website", website_match
    else:
        score, channel, evidence = 10, "default_twitter_dm", None

    return ScoreTrace(
        value=float(score),
        formula="bio regex: email=100 > telegram=80 > collab_kw=60 > website=40 > default_dm=10",
        inputs={
            "bio_length": len(bio),
            "email_found": bool(email_match),
            "telegram_found": bool(tg_match),
            "collab_keyword_found": bool(collab_match),
            "website_found": bool(website_match),
            "channel": channel,
            "evidence": evidence,
        },
        calculation=f"channel={channel} → score {score}",
        confidence="low" if not bio else "high",
        notes="empty bio — defaulting to Twitter DM fallback" if not bio else None,
    )


# ---- Tweet patterns for Promo Willingness ----

_TWEET_SPONSOR_PATTERNS = re.compile(
    r"#ad\b|#sponsored\b|#sponsor\b|#partnership\b|#collab\b|"
    r"\bin\s+partnership\s+with\b|"
    r"\bsponsored\s+by\b|"
    r"\bbrought\s+to\s+you\s+by\b|"
    r"\bis\s+sponsoring\b|"
    r"\bpaid\s+partnership\b|"
    r"\bambassador\s+for\b|"
    r"\bofficial\s+ambassador\b|"
    r"(合作推广|赞助内容|赞助播报)",
    re.IGNORECASE,
)

_TWEET_REVIEW_PATTERNS = re.compile(
    r"\b(review|deep\s*dive|analysis|thread\s+on|thoughts\s+on|my\s+take\s+on|"
    r"let'?s\s+talk\s+about|breakdown\s+of|introducing|just\s+tried|"
    r"tested|explored|checked\s+out)\b|"
    r"(测评|深度分析|解读|评测|试用|项目介绍|简介)",
    re.IGNORECASE,
)

_TWEET_MENTION = re.compile(r"@([A-Za-z0-9_]{1,15})")


def calculate_promo_willingness(kol: KolRaw) -> ScoreTrace:
    """Layer 3.2 (redesigned 2026-04-09) — scan recent posts for sponsor/review.

    Replaces `calculate_promo_history`, which depended on a Phase 1d pass that
    only ran on 50/680 KOLs. This version works directly on any cached tweets,
    combining Phase 1d classifications (when available) with raw text regex
    fallback.

    Bucket (first match wins):
      ≥ 1 post with explicit sponsor disclosure             → 90
        (either phase1d classification.promo_match or text regex)
      ≥ 3 authored posts combining review-keyword + @mention → 60
      authored posts exist but no sponsor/review signal     → 30
      no cached tweets                                      → null
    """
    posts = kol.recent_posts[:20]
    if not posts:
        return ScoreTrace(
            value=None,
            formula="scan: sponsor(90) > review+mention(60) > authored_only(30) > null",
            inputs={"post_count": 0},
            calculation="no cached tweets — cannot scan for promo signal",
            confidence="low",
            notes="phase_1d_pending: no tweets in DB for this KOL",
        )

    # ---- Tier 1: explicit sponsor disclosure ----
    sponsor_hits: list[str] = []
    for t in posts:
        if t.classification and t.classification.promo_match:
            sponsor_hits.append(t.classification.promo_match)
            continue
        text = t.text or ""
        m = _TWEET_SPONSOR_PATTERNS.search(text)
        if m:
            sponsor_hits.append(m.group(0))

    if sponsor_hits:
        return ScoreTrace(
            value=90.0,
            formula="scan: sponsor(90) > review+mention(60) > authored_only(30) > null",
            inputs={
                "post_count": len(posts),
                "sponsor_hit_count": len(sponsor_hits),
                "evidence": sponsor_hits[:3],
                "reason": "explicit_sponsor_disclosure",
            },
            calculation=f"{len(sponsor_hits)} post(s) with sponsor disclosure → 90",
            confidence="high",
            notes=None,
        )

    # ---- Tier 2: review content + project @-mentions ----
    authored = [t for t in posts if t.is_authored]
    self_handle = kol.handle.lower()
    review_hits = 0
    mention_posts = 0
    for t in authored:
        text = t.text or ""
        has_review = bool(_TWEET_REVIEW_PATTERNS.search(text))
        mentions_other = any(
            m.lower() != self_handle for m in _TWEET_MENTION.findall(text)
        )
        if mentions_other:
            mention_posts += 1
        if has_review and mentions_other:
            review_hits += 1

    if review_hits >= 3:
        return ScoreTrace(
            value=60.0,
            formula="scan: sponsor(90) > review+mention(60) > authored_only(30) > null",
            inputs={
                "post_count": len(posts),
                "authored_count": len(authored),
                "review_with_mention_count": review_hits,
                "mention_post_count": mention_posts,
                "reason": "review_content_with_project_mentions",
            },
            calculation=f"{review_hits} authored post(s) with review kw + @mention → 60",
            confidence="medium",
            notes="inferred willingness from review pattern — not a confirmed paid sponsor",
        )

    # ---- Tier 3: authored posts exist but no promo/review signal ----
    if authored:
        return ScoreTrace(
            value=30.0,
            formula="scan: sponsor(90) > review+mention(60) > authored_only(30) > null",
            inputs={
                "post_count": len(posts),
                "authored_count": len(authored),
                "review_with_mention_count": review_hits,
                "mention_post_count": mention_posts,
                "reason": "only_own_opinions",
            },
            calculation=f"{len(authored)} authored posts, 0 sponsor / {review_hits} review+mention → 30",
            confidence="medium",
            notes=None,
        )

    # No authored posts at all (all retweets/replies).
    return ScoreTrace(
        value=30.0,
        formula="scan: sponsor(90) > review+mention(60) > authored_only(30) > null",
        inputs={
            "post_count": len(posts),
            "authored_count": 0,
            "reason": "no_authored_posts_cached",
        },
        calculation="all cached posts are retweets/replies → default 30",
        confidence="low",
        notes="no authored posts to analyze",
    )


_ACCESSIBILITY_BASE_BY_TIER: dict[str, int] = {
    "Nano":  90,
    "Micro": 70,
    "Macro": 40,
    "Mega":  15,
}
_ACCESSIBILITY_MUTUAL_BONUS = 15


def calculate_accessibility(kol: KolRaw) -> ScoreTrace:
    """Layer 3.3 (redesigned 2026-04-09) — tier inverse + mutual member bonus.

    Replaces the old `response_likelihood` heuristic (which itself tried to
    encode a similar idea with more moving parts that added no signal). This
    version is a plain table lookup plus one modifier.

    Base by tier (smaller = more responsive baseline):
      Nano → 90 | Micro → 70 | Macro → 40 | Mega → 15

    + 15 if KOL is in the mutual subgraph (t1_mutual_count ≥ 1) — signals
    that Dov can reach them via warm intro from an existing contact.

    Capped at 100. Returns null if tier is unknown.
    """
    tier = kol.profile.tier
    if tier is None:
        return ScoreTrace(
            value=None,
            formula="base_by_tier + (15 if mutual_member else 0), cap 100",
            inputs={"tier": None},
            calculation="tier not set — cannot compute base",
            confidence="low",
            notes="tier_unknown",
        )

    base = _ACCESSIBILITY_BASE_BY_TIER.get(tier, 0)
    ns = kol.network_stats
    is_mutual = ns is not None and ns.t1_mutual_count > 0
    bonus = _ACCESSIBILITY_MUTUAL_BONUS if is_mutual else 0
    score = min(100.0, float(base + bonus))

    return ScoreTrace(
        value=score,
        formula="base_by_tier(Nano=90/Micro=70/Macro=40/Mega=15) + 15*is_mutual_member, cap 100",
        inputs={
            "tier": tier,
            "base": base,
            "is_mutual_member": is_mutual,
            "t1_mutual_count": ns.t1_mutual_count if ns else 0,
            "bonus": bonus,
        },
        calculation=f"{base} + {bonus} (mutual={is_mutual}) = {score:.0f}",
        confidence="high",
        notes=None,
    )


def compute_cooperability_score(traces: dict[str, ScoreTrace]) -> tuple[float | None, ConfidenceLiteral]:
    """Same MIN_SUB_SCORES_FOR_AGGREGATE rule as Layer 1."""
    available = [(k, t.value) for k, t in traces.items() if t.value is not None]
    if len(available) < MIN_SUB_SCORES_FOR_AGGREGATE:
        return None, "low"
    total_w = sum(LAYER_3_WEIGHTS[k] for k, _ in available)
    weighted_sum = sum(LAYER_3_WEIGHTS[k] * v for k, v in available)
    score = round(weighted_sum / total_w, 2)
    conf = _min_confidence([traces[k].confidence for k, _ in available])
    return score, conf


# ============================================================
# Confidence helpers
# ============================================================

_CONFIDENCE_ORDER: list[ConfidenceLiteral] = ["high", "medium", "low", "n/a"]


def _min_confidence(confs: list[ConfidenceLiteral]) -> ConfidenceLiteral:
    """Return the LOWEST (most conservative) confidence among a list."""
    if not confs:
        return "n/a"
    # Drop n/a values since they mean "not applicable", not "low"
    filtered = [c for c in confs if c != "n/a"]
    if not filtered:
        return "n/a"
    ranks = {c: i for i, c in enumerate(_CONFIDENCE_ORDER)}
    return max(filtered, key=lambda c: ranks[c])


# ============================================================
# Top-level orchestration
# ============================================================


def score_kol(kol: KolRaw) -> ScoredKol:
    """Score a KOL across all three layers. See spec §7."""
    # Layer 1
    layer1_traces = {
        "engagement_quality_ratio": calculate_engagement_quality_ratio(kol),
        "content_originality":      calculate_content_originality(kol),
        "audience_authenticity":    calculate_audience_authenticity(kol),
        "sector_relevance":         calculate_sector_relevance(kol),
        "network_position":         calculate_network_position(kol),
    }
    quality_score, quality_conf = compute_quality_score(layer1_traces)

    # Layer 2
    if kol.has_onchain:
        layer2_traces = {
            "wallet_content_alignment": calculate_wallet_content_alignment(kol),
            "onchain_activity_depth":   calculate_onchain_activity_depth(kol),
            "campaign_impact_score":    calculate_campaign_impact_score(kol),
        }
        onchain_score, onchain_conf = compute_onchain_score(layer2_traces, wallet_public=True)
    else:
        layer2_traces = None
        onchain_score, onchain_conf = None, "n/a"

    # Layer 3 (redesigned 2026-04-09)
    layer3_traces = {
        "contact_signal_strength": calculate_contact_signal_strength(kol),
        "promo_willingness":       calculate_promo_willingness(kol),
        "accessibility":           calculate_accessibility(kol),
    }
    coop_score, coop_conf = compute_cooperability_score(layer3_traces)

    return ScoredKol(
        handle=kol.handle,
        quality_score=quality_score,
        cooperability_score=coop_score,
        onchain_score=onchain_score,
        quality_trace=layer1_traces,
        cooperability_trace=layer3_traces,
        onchain_trace=layer2_traces,
        quality_confidence=quality_conf,
        cooperability_confidence=coop_conf,
        onchain_confidence=onchain_conf,
    )


# ============================================================
# Persistence: write ScoredKol back to Supabase
# ============================================================


def _trace_dict_to_json(traces: dict[str, ScoreTrace] | None) -> dict[str, Any] | None:
    """Serialize a trace dict to JSON-ready nested dicts for JSONB storage."""
    if traces is None:
        return None
    return {k: t.model_dump(mode="json") for k, t in traces.items()}


_SCORE_TRACE_KEYS = {"quality", "cooperability", "onchain"}


def write_score_to_db(scored: ScoredKol) -> None:
    """Upsert a ScoredKol's three scores + full traces to users table.

    Merges into users.score_traces JSONB rather than replacing, so that
    Phase 1d classifier outputs (stored under keys like `phase1d_*`) are
    preserved across re-scoring runs.

    Columns written:
      quality_score / cooperability_score / onchain_score
      quality_confidence / cooperability_confidence / onchain_confidence
      score_traces (JSONB — merged: scoring keys replaced, phase1d keys preserved)
      scored_at / scored_with_version
    """
    from pipeline.db import get_client

    scoring_traces = {
        "quality": _trace_dict_to_json(scored.quality_trace),
        "cooperability": _trace_dict_to_json(scored.cooperability_trace),
        "onchain": _trace_dict_to_json(scored.onchain_trace),
    }

    c = get_client()

    # Fetch existing score_traces and preserve non-scoring keys (e.g. phase1d_*)
    existing = c.table("users").select("score_traces").eq("handle", scored.handle).execute()
    current = (existing.data[0].get("score_traces") if existing.data else None) or {}
    preserved = {k: v for k, v in current.items() if k not in _SCORE_TRACE_KEYS}
    merged = {**preserved, **scoring_traces}

    payload: dict[str, Any] = {
        "quality_score": scored.quality_score,
        "cooperability_score": scored.cooperability_score,
        "onchain_score": scored.onchain_score,
        "quality_confidence": scored.quality_confidence,
        "cooperability_confidence": scored.cooperability_confidence,
        "onchain_confidence": scored.onchain_confidence,
        "score_traces": merged,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "scored_with_version": scored.scored_with_version,
    }

    c.table("users").update(payload).eq("handle", scored.handle).execute()


# ============================================================
# CLI smoke test
# ============================================================


if __name__ == "__main__":
    import sys

    from scoring.load_kol import load_kol_raw

    handle = sys.argv[1] if len(sys.argv) > 1 else "btcdayu"
    kol = load_kol_raw(handle)
    if kol is None:
        print(f"@{handle}: not found in DB")
        sys.exit(1)

    result = score_kol(kol)

    print(f"@{result.handle}  (scored_with_version={result.scored_with_version})")
    print(f"  Quality:       {result.quality_score}  ({result.quality_confidence})")
    print(f"  Cooperability: {result.cooperability_score}  ({result.cooperability_confidence})")
    print(f"  On-chain:      {result.onchain_score}  ({result.onchain_confidence})")

    print("\n  Layer 1 traces:")
    for name, trace in result.quality_trace.items():
        v = f"{trace.value}" if trace.value is not None else "null"
        print(f"    {name:<26} = {v:<8} [{trace.confidence}]")
        if trace.notes:
            print(f"      note: {trace.notes}")
        if trace.value is not None:
            print(f"      calc: {trace.calculation}")

    print("\n  Layer 3 traces:")
    for name, trace in result.cooperability_trace.items():
        v = f"{trace.value}" if trace.value is not None else "null"
        print(f"    {name:<26} = {v:<8} [{trace.confidence}]")
        if trace.notes:
            print(f"      note: {trace.notes}")
        if trace.value is not None:
            print(f"      calc: {trace.calculation}")
