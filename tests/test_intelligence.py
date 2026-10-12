"""Tests for intelligence, classification, scoring, cross-modal deduplication, and clustering."""

from jyot_monitor.intelligence.classification import TopicClassifier
from jyot_monitor.intelligence.scoring import PriorityScorer
from jyot_monitor.intelligence.deduplication import MultimodalDeduplicator
from jyot_monitor.intelligence.clustering import StoryClusterer
from jyot_monitor.intelligence.verification import UrgencyVerifier
from jyot_monitor.schemas import ItemSchema, ProcessingStatus


def test_topic_classification():
    classifier = TopicClassifier()

    food_res = classifier.classify("FDA announces Class I recall of baby formula due to cronobacter contamination.")
    assert food_res.subtopic == "Food & Drug Safety"

    product_res = classifier.classify("CPSC warns of severe fire hazard in rechargeable lithium battery pack.")
    assert product_res.subtopic == "Consumer Product Hazard"

    civic_res = classifier.classify("Boil water advisory issued by municipal utility following water main break.")
    assert civic_res.subtopic == "Civic & Infrastructure Outage"


def test_scoring_with_non_llm_weights():
    scorer = PriorityScorer()

    # Official regulator with life-threatening severity
    official_score = scorer.score(
        text="Class I recall: fatal bacterial contamination detected in infant medicine batch.",
        source="fda",
        corroboration_count=2,
        has_verified_batch=True,
    )
    assert official_score.urgency_score >= 80.0
    assert official_score.breakdown["source_credibility_pts"] == 20.0
    assert official_score.breakdown["corroboration_bonus"] == 8.0

    # Social rumor without verification
    social_score = scorer.score(
        text="I heard someone said my heater was smoking.",
        source="social",
        corroboration_count=1,
    )
    assert social_score.urgency_score < official_score.urgency_score
    assert social_score.breakdown["source_credibility_pts"] == 10.0


def test_cross_modal_deduplication():
    dedup = MultimodalDeduplicator()

    # 1. Text vs Text fuzzy
    t1 = "Urgent recall of HeatPro space heater model H400 due to fire"
    t2 = "Urgent recall of HeatPro space heater model H400 due to fire hazard"
    is_dup, match_type, sim = dedup.check_duplicate(t1, t2)
    assert is_dup
    assert match_type == "text_fuzzy"
    assert sim > 85.0

    # 2. Cross-modal: OCR text vs Post text
    post_text = "HeatPro ceramic space heater model H400 recall notice"
    ocr_text = "CONSUMER PRODUCT SAFETY COMMISSION: HeatPro ceramic space heater model H400 recall notice"
    is_dup, match_type, sim = dedup.check_duplicate(text_a="", text_b=post_text, ocr_text_a=ocr_text)
    assert is_dup
    assert "cross_modal" in match_type


def test_clustering_and_representative():
    clusterer = StoryClusterer()

    item_official = ItemSchema(
        item_id="official_01",
        source="cpsc",
        source_url="https://cpsc.gov/recall",
        published_at="2026-10-01T00:00:00Z",
        text="Official CPSC Notice: HeatPro heater model H400 recalled due to fire risk.",
        content_hash="h1",
    )
    item_social = ItemSchema(
        item_id="social_01",
        source="social",
        source_url="https://social.com/1",
        published_at="2026-10-01T01:00:00Z",
        text="Heater recalled HeatPro model H400 fire hazard.",
        content_hash="h2",
    )

    clusters = clusterer.cluster_items([item_official, item_social])
    assert len(clusters) == 1
    # Official source must be selected as representative
    assert clusters[0].representative_item_id == "official_01"
    assert len(clusters[0].member_item_ids) == 2


def test_urgency_verifier():
    verifier = UrgencyVerifier()
    scorer = PriorityScorer()

    unverified_item = ItemSchema(
        item_id="rumor_1",
        source="social",
        source_url="https://x.com/rumor",
        published_at="2026-10-01T00:00:00Z",
        text="Fatal poison in all local milk bottles panic everywhere!",
        content_hash="hrumor",
    )
    init_score = scorer.score(unverified_item.text, source=unverified_item.source)

    # Self-critique should downgrade uncorroborated sensational rumor
    is_ver, adj_urgency, flags, expl = verifier.critique_claim(
        unverified_item, init_score, corroborating_items=[]
    )
    assert not is_ver
    assert "single_unverified_source" in flags
    assert adj_urgency < init_score.urgency_score
