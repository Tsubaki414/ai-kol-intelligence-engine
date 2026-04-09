"""
Load a normalized KolRaw from Supabase.

Merges data across `users`, `tweets`, and `follows` tables into the
Pydantic schema from scoring/schema.py. This is the bridge between the
DB layer (pipeline/db.py) and the scoring layer (scoring/score_kol.py).

Usage:
    from scoring.load_kol import load_kol_raw
    kol = load_kol_raw("btcdayu")
    if kol is None:
        print("not in DB")
    else:
        from scoring.score_kol import score_kol
        result = score_kol(kol)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.db import get_client  # noqa: E402
from scoring.schema import (  # noqa: E402
    ContactSignals,
    CooperabilityHardFilter,
    KolRaw,
    NetworkStats,
    PastRateDisclosures,
    PostClassification,
    Profile,
    PromoHistory90d,
    PublicMetrics,
    ReferencedTweet,
    Tweet,
)


def load_kol_raw(handle: str) -> KolRaw | None:
    """Load a single KolRaw from Supabase. Returns None if the handle isn't in `users`."""
    handle = handle.lstrip("@").lower().strip()
    if not handle:
        return None

    c = get_client()

    # 1. users row (profile + classification + cooperability hard filter)
    r = c.table("users").select("*").eq("handle", handle).execute()
    if not r.data:
        return None
    u: dict[str, Any] = r.data[0]

    # 2. tweets rows
    t_rows = (
        c.table("tweets")
        .select("*")
        .eq("author_handle", handle)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
    )

    # 3. network_stats derived from follows
    network_stats = _derive_network_stats(c, handle, u.get("cluster_id"))

    # 4. Build Profile
    profile = Profile(
        followers=u.get("followers_count") or 0,
        following=u.get("following_count") or 0,
        joined=str(u["joined_at"]) if u.get("joined_at") else None,
        verified=bool(u.get("verified") or False),
        bio=u.get("bio") or "",
        is_dm_open=None,  # not stored in v1 — will be added when Phase 1d profile fetch runs
        tier=u.get("tier"),  # may be None for unclassified
    )

    # 5. Cooperability hard filter + contact signals (both derive from users.cooperability)
    coop_raw = u.get("cooperability") or {}
    if isinstance(coop_raw, str):
        # Supabase sometimes returns JSONB as string; parse
        import json as _json

        try:
            coop_raw = _json.loads(coop_raw)
        except Exception:
            coop_raw = {}

    coop_hf: CooperabilityHardFilter | None = None
    if coop_raw.get("is_contactable") is not None:
        coop_hf = CooperabilityHardFilter(
            is_contactable=bool(coop_raw.get("is_contactable", False)),
            accepts_paid_promos=bool(coop_raw.get("accepts_paid_promos", False)),
            contact_method=coop_raw.get("contact_method") or "none_public",
            public_email=coop_raw.get("public_email"),
            public_telegram=coop_raw.get("public_telegram"),
        )

    # ContactSignals: prefer Phase 1d outputs (stored in users.score_traces under
    # phase1d_contact_signals) over v1 classifier cooperability fields.
    score_traces_blob = u.get("score_traces") or {}
    if isinstance(score_traces_blob, str):
        import json as _json

        try:
            score_traces_blob = _json.loads(score_traces_blob)
        except Exception:
            score_traces_blob = {}

    phase1d_contact = score_traces_blob.get("phase1d_contact_signals") or {}
    contact_signals = ContactSignals(
        email_in_bio=phase1d_contact.get("email_in_bio") or coop_raw.get("public_email"),
        telegram_handle=phase1d_contact.get("telegram_handle") or coop_raw.get("public_telegram"),
        website=phase1d_contact.get("website"),
    )

    # Phase 1d: past rate disclosures
    phase1d_rates = score_traces_blob.get("phase1d_past_rate_disclosures") or {}
    past_rate_disclosures: PastRateDisclosures | None = None
    if phase1d_rates:
        past_rate_disclosures = PastRateDisclosures(
            has_public_rate_card=bool(phase1d_rates.get("has_public_rate_card", False)),
            inferred_from_past_promos=bool(phase1d_rates.get("inferred_from_past_promos", False)),
            rate_card_url=phase1d_rates.get("rate_card_url"),
        )

    # Phase 1d: promo history 90d (derived from tweet classifications)
    phase1d_promo = score_traces_blob.get("phase1d_promo_history_90d") or {}
    promo_history_90d: PromoHistory90d | None = None
    if phase1d_promo:
        promo_history_90d = PromoHistory90d(
            promo_match_count=int(phase1d_promo.get("promo_match_count", 0)),
            promo_examples=list(phase1d_promo.get("promo_examples") or [])[:5],
        )

    # 6. Build recent_posts list
    recent_posts: list[Tweet] = []
    for t in t_rows:
        pm = t.get("public_metrics") or {}
        if isinstance(pm, str):
            import json as _json

            try:
                pm = _json.loads(pm)
            except Exception:
                pm = {}
        refs_raw = t.get("referenced_tweets") or []
        if isinstance(refs_raw, str):
            import json as _json

            try:
                refs_raw = _json.loads(refs_raw)
            except Exception:
                refs_raw = []

        # Parse Phase 1d classification if present
        cls_raw = t.get("classification")
        if isinstance(cls_raw, str):
            import json as _json

            try:
                cls_raw = _json.loads(cls_raw)
            except Exception:
                cls_raw = None

        classification: PostClassification | None = None
        if cls_raw and isinstance(cls_raw, dict) and cls_raw.get("content_class"):
            try:
                classification = PostClassification(
                    content_class=cls_raw.get("content_class"),
                    is_ai_generated_suspected=bool(cls_raw.get("is_ai_generated_suspected", False)),
                    sector=cls_raw.get("sector") or "other",
                    is_ai_crypto_related=bool(cls_raw.get("is_ai_crypto_related", False)),
                    originality_score_raw=int(cls_raw.get("originality_score_raw", 0)),
                    promo_match=cls_raw.get("promo_match"),
                    mentioned_tokens=cls_raw.get("mentioned_tokens") or [],
                )
            except Exception:
                classification = None

        recent_posts.append(
            Tweet(
                id=t.get("tweet_id", ""),
                created_at=t.get("created_at"),
                text=t.get("text") or "",
                lang=t.get("lang"),
                referenced_tweets=[
                    ReferencedTweet(type=r["type"], id=str(r["id"]))
                    for r in refs_raw
                    if isinstance(r, dict) and r.get("type") and r.get("id")
                ],
                public_metrics=PublicMetrics(
                    like_count=pm.get("like_count", 0),
                    reply_count=pm.get("reply_count", 0),
                    retweet_count=pm.get("retweet_count", 0),
                    quote_count=pm.get("quote_count", 0),
                ),
                classification=classification,
            )
        )

    return KolRaw(
        handle=handle,
        profile=profile,
        contact_signals=contact_signals,
        cooperability_hard_filter=coop_hf,
        recent_posts=recent_posts,
        network_stats=network_stats,
        posts_last_30d=None,        # TODO: derive from recent_posts aggregate
        reply_stream_sample=None,   # TODO: fetch via /tweets/search/recent
        promo_history_90d=promo_history_90d,
        past_rate_disclosures=past_rate_disclosures,
        onchain=None,               # Layer 2 deferred to post-bootstrap
    )


def _derive_network_stats(
    client, handle: str, self_cluster: int | None
) -> NetworkStats:
    """Derive a KOL's network_stats from the `follows` table.

    T1 mutual = intersection of who-they-follow AND who-follows-them within the DB.
    Cross-cluster count = mutuals whose cluster_id differs from this KOL's.
    """
    # Followees (out-edges)
    r1 = client.table("follows").select("followee_handle").eq("follower_handle", handle).execute()
    followees: set[str] = {row["followee_handle"] for row in r1.data}

    # Followers (in-edges)
    r2 = client.table("follows").select("follower_handle").eq("followee_handle", handle).execute()
    followers: set[str] = {row["follower_handle"] for row in r2.data}

    mutuals = sorted(followees & followers)
    t1_count = len(mutuals)

    cross_count = 0
    if self_cluster is not None and mutuals:
        r3 = (
            client.table("users")
            .select("handle, cluster_id")
            .in_("handle", mutuals)
            .execute()
        )
        for m in r3.data:
            m_cluster = m.get("cluster_id")
            if m_cluster is not None and m_cluster != self_cluster:
                cross_count += 1

    bridge_ratio = (cross_count / t1_count) if t1_count > 0 else 0.0

    return NetworkStats(
        t1_mutual_count=t1_count,
        cross_cluster_mutual_count=cross_count,
        bridge_ratio=bridge_ratio,
        cluster_id=self_cluster,
    )


if __name__ == "__main__":
    # CLI smoke test: load a handle and print key fields
    import json

    handle = sys.argv[1] if len(sys.argv) > 1 else "btcdayu"
    kol = load_kol_raw(handle)
    if kol is None:
        print(f"@{handle}: not found in DB")
        sys.exit(1)

    print(f"@{kol.handle}")
    print(f"  tier: {kol.profile.tier}")
    print(f"  followers: {kol.profile.followers:,}")
    print(f"  recent_posts: {len(kol.recent_posts)} (authored: {sum(1 for t in kol.recent_posts if t.is_authored)})")
    if kol.network_stats:
        print(f"  network_stats:")
        print(f"    t1_mutual_count: {kol.network_stats.t1_mutual_count}")
        print(f"    bridge_ratio: {kol.network_stats.bridge_ratio:.3f}")
        print(f"    cluster_id: {kol.network_stats.cluster_id}")
    if kol.cooperability_hard_filter:
        print(f"  coop hard filter: contactable={kol.cooperability_hard_filter.is_contactable}, "
              f"paid={kol.cooperability_hard_filter.accepts_paid_promos}, "
              f"method={kol.cooperability_hard_filter.contact_method}")
