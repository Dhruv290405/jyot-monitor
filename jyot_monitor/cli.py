"""Command-line interface implementing the required Jyot Monitor CLI contract."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from jyot_monitor.agent.controller import AgentController
from jyot_monitor.agent.planner import LLMPlanner
from jyot_monitor.agent.tools import ToolRegistry
from jyot_monitor.agent.trace import TraceLogger
from jyot_monitor.alerting.approval import AlertApprovalService
from jyot_monitor.alerting.proposals import ProposalManager
from jyot_monitor.config import get_config
from jyot_monitor.database import Database
from jyot_monitor.extraction.pdf import PDFProcessor
from jyot_monitor.extraction.preprocess import ImagePreprocessor
from jyot_monitor.extraction.router import OCRRouter
from jyot_monitor.extraction.tesseract_engine import TesseractEngine
from jyot_monitor.extraction.vision_engine import VisionEngine
from jyot_monitor.ingestion.replay import ReplayIngester
from jyot_monitor.ingestion.rss import RSSIngester
from jyot_monitor.intelligence.classification import TopicClassifier
from jyot_monitor.intelligence.clustering import StoryClusterer
from jyot_monitor.intelligence.deduplication import MultimodalDeduplicator
from jyot_monitor.intelligence.scoring import PriorityScorer
from jyot_monitor.intelligence.verification import UrgencyVerifier
from jyot_monitor.reporting.change_tracking import ChangeTracker
from jyot_monitor.reporting.digest import DigestGenerator
from jyot_monitor.safety.injection import InjectionDetector
from jyot_monitor.safety.network import SafeFetcher
from jyot_monitor.safety.pii import PIIRedactor
from jyot_monitor.safety.spam import SpamDetector
from jyot_monitor.schemas import ItemSchema, StoryCluster

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("jyot_monitor")


def build_system(db_path: str, is_replay: bool = False, run_id: Optional[str] = None, fault_injection: bool = False):
    """Instantiates and wires all system components."""
    config = get_config()
    if fault_injection:
        config.fault_injection_enabled = True
    db = Database(db_path=db_path)
    preprocessor = ImagePreprocessor()
    tesseract_engine = TesseractEngine(
        tesseract_cmd=config.tesseract_cmd, preprocessor=preprocessor
    )
    vision_engine = VisionEngine(
        base_url=config.ollama_base_url,
        model_name=config.ollama_vision_model,
        timeout_seconds=config.agent_step_timeout_seconds,
        is_replay_mode=is_replay,
    )
    ocr_router = OCRRouter(
        tesseract_engine=tesseract_engine,
        vision_engine=vision_engine,
        preprocessor=preprocessor,
    )
    pdf_processor = PDFProcessor()
    safe_fetcher = SafeFetcher(timeout_seconds=config.agent_step_timeout_seconds)

    deduplicator = MultimodalDeduplicator()
    clusterer = StoryClusterer(deduplicator=deduplicator)
    classifier = TopicClassifier()
    scorer = PriorityScorer()
    verifier = UrgencyVerifier(urgency_threshold=config.alert_urgency_threshold)
    redactor = PIIRedactor()
    injection_detector = InjectionDetector()
    spam_detector = SpamDetector()

    proposal_manager = ProposalManager(db=db, redactor=redactor)
    approval_service = AlertApprovalService(db=db)

    tool_registry = ToolRegistry(
        db=db,
        router=ocr_router,
        vision_engine=vision_engine,
        classifier=classifier,
        scorer=scorer,
        verifier=verifier,
        proposal_manager=proposal_manager,
        safe_fetcher=safe_fetcher,
        pdf_processor=pdf_processor,
        is_replay_mode=is_replay,
        fault_injection=fault_injection,
    )

    actual_run_id = run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    tracer = TraceLogger(trace_dir=config.trace_dir, run_id=actual_run_id)

    planner = LLMPlanner(
        base_url=config.ollama_base_url,
        model_name=config.ollama_planner_model,
        timeout_seconds=config.agent_step_timeout_seconds,
        is_replay_mode=is_replay,
    )

    controller = AgentController(
        planner=planner,
        tools=tool_registry,
        tracer=tracer,
        injection_detector=injection_detector,
        spam_detector=spam_detector,
        max_steps_per_item=config.max_steps_per_item,
        item_budget_usd=config.max_cost_per_item_usd,
        run_budget_usd=config.max_cost_per_run_usd,
    )

    change_tracker = ChangeTracker()
    digest_generator = DigestGenerator(
        db=db, change_tracker=change_tracker, redactor=redactor
    )

    return {
        "config": config,
        "db": db,
        "run_id": actual_run_id,
        "controller": controller,
        "tracer": tracer,
        "clusterer": clusterer,
        "classifier": classifier,
        "scorer": scorer,
        "proposal_manager": proposal_manager,
        "approval_service": approval_service,
        "digest_generator": digest_generator,
        "deduplicator": deduplicator,
        "safe_fetcher": safe_fetcher,
    }


def handle_run(args) -> int:
    """Executes ingestion, agent processing, clustering, and digest generation."""
    is_replay = bool(args.replay)
    fault_injection = getattr(args, "fault_injection", False)
    if fault_injection and not is_replay:
        print("Error: --fault-injection can only be used with --replay", file=sys.stderr)
        return 1
    if fault_injection:
        logger.info("Fault-injection mode enabled for replay run")
    sys_components = build_system(db_path=args.db, is_replay=is_replay, fault_injection=fault_injection)
    db: Database = sys_components["db"]
    controller: AgentController = sys_components["controller"]
    clusterer: StoryClusterer = sys_components["clusterer"]
    classifier: TopicClassifier = sys_components["classifier"]
    digest_gen: DigestGenerator = sys_components["digest_generator"]
    run_id: str = sys_components["run_id"]

    logger.info(f"Starting run {run_id} (Replay: {is_replay})")

    # Ingestion
    items: List[ItemSchema] = []
    if args.replay:
        logger.info(f"Ingesting via offline replay from: {args.replay}")
        replay_ingester = ReplayIngester(args.replay)
        items = replay_ingester.load_items()
    elif args.sources:
        logger.info(f"Ingesting from live sources configuration: {args.sources}")
        with open(args.sources, "r", encoding="utf-8") as f:
            sources_config = json.load(f)
        rss_ingester = RSSIngester(db=db)
        for src in sources_config.get("sources", []):
            if src.get("enabled", True):
                items.extend(rss_ingester.fetch_feed(src))
    else:
        logger.error("Must specify either --sources or --replay")
        return 1

    if args.max_items and len(items) > args.max_items:
        items = items[: args.max_items]

    logger.info(f"Loaded {len(items)} items for processing.")

    # Clustering & Agent Processing
    existing_clusters = db.list_clusters()
    current_clusters = clusterer.cluster_items(items, existing_clusters=existing_clusters)

    # Map item to its cluster ID
    item_cluster_map = {}
    for c in current_clusters:
        for it_id in c.member_item_ids:
            item_cluster_map[it_id] = c

    # Process each item through Agent loop
    for item in items:
        # Save or resume
        db.save_item(item)
        target_cluster = item_cluster_map.get(item.item_id)
        cluster_id = target_cluster.cluster_id if target_cluster else "cluster_unassigned"

        status, state = controller.process_item(item, cluster_id=cluster_id)
        db.save_item(item)

        # Update cluster max urgency and classification topic
        if target_cluster:
            item_urgency = state.get("urgency_score", 0.0)
            if item_urgency > target_cluster.max_urgency:
                target_cluster.max_urgency = item_urgency
            if target_cluster.topic == "Safety Story":
                cls_res = classifier.classify(item.text)
                target_cluster.topic = cls_res.subtopic

    # Save updated clusters
    for c in current_clusters:
        db.save_cluster(c)

    # Generate Digest
    digest_output_path = Path(args.digest)
    digest_output_path.parent.mkdir(parents=True, exist_ok=True)
    mode_str = "replay" if is_replay else "live"
    digest_content = digest_gen.generate_digest(
        run_id=run_id,
        clusters=current_clusters,
        run_mode=mode_str,
    )

    with open(digest_output_path, "w", encoding="utf-8") as f:
        f.write(digest_content)

    logger.info(f"Digest generated successfully: {digest_output_path}")
    logger.info(f"Traces written to: traces/{run_id}.jsonl")
    return 0


def handle_approve(args) -> int:
    """Approves a pending alert proposal."""
    sys_components = build_system(db_path=args.db)
    service: AlertApprovalService = sys_components["approval_service"]
    reviewer = args.reviewer or "human_operator"

    success, msg, _ = service.approve_proposal(args.proposal_id, reviewer=reviewer)
    if success:
        print(f"SUCCESS: {msg}")
        return 0
    else:
        print(f"FAILED: {msg}", file=sys.stderr)
        return 1


def handle_reject(args) -> int:
    """Rejects an alert proposal."""
    sys_components = build_system(db_path=args.db)
    service: AlertApprovalService = sys_components["approval_service"]
    reviewer = args.reviewer or "human_operator"

    success, msg, _ = service.reject_proposal(
        args.proposal_id, reviewer=reviewer, reason=args.reason
    )
    if success:
        print(f"SUCCESS: {msg}")
        return 0
    else:
        print(f"FAILED: {msg}", file=sys.stderr)
        return 1


def handle_eval(args) -> int:
    """Runs the evaluation harness."""
    from jyot_monitor.evaluation.run_eval import run_evaluation_suite
    return run_evaluation_suite(
        dataset_dir=args.dataset,
        report_output_path=args.report,
        db_path=args.db,
    )


def main():
    parser = argparse.ArgumentParser(
        prog="jyot_monitor",
        description="Jyot Multimodal Agentic Monitor & Digest",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. run command
    run_parser = subparsers.add_parser("run", help="Run ingestion, agent loop, and generate digest")
    run_parser.add_argument("--sources", type=str, help="Path to sources.json configuration file")
    run_parser.add_argument("--replay", type=str, help="Path to replay fixtures directory or JSON file")
    run_parser.add_argument("--digest", type=str, required=True, help="Destination Markdown digest file path")
    run_parser.add_argument("--max-items", type=int, default=None, help="Maximum items to ingest")
    run_parser.add_argument("--db", type=str, default="data/jyot_monitor.db", help="SQLite database path")
    run_parser.add_argument("--fault-injection", action="store_true", help="Inject controlled deterministic failure during replay runs only (implies --replay)")

    # 2. approve command
    approve_parser = subparsers.add_parser("approve", help="Approve an alert proposal from the queue")
    approve_parser.add_argument("proposal_id", type=str, help="ID of proposal to approve")
    approve_parser.add_argument("--reviewer", type=str, default="operator", help="Reviewer username")
    approve_parser.add_argument("--db", type=str, default="data/jyot_monitor.db", help="SQLite database path")

    # 3. reject command
    reject_parser = subparsers.add_parser("reject", help="Reject an alert proposal")
    reject_parser.add_argument("proposal_id", type=str, help="ID of proposal to reject")
    reject_parser.add_argument("--reviewer", type=str, default="operator", help="Reviewer username")
    reject_parser.add_argument("--reason", type=str, default=None, help="Reason for rejection")
    reject_parser.add_argument("--db", type=str, default="data/jyot_monitor.db", help="SQLite database path")

    # 4. eval command
    eval_parser = subparsers.add_parser("eval", help="Run evaluation harness against gold dataset")
    eval_parser.add_argument("--dataset", type=str, required=True, help="Path to gold dataset directory")
    eval_parser.add_argument("--report", type=str, required=True, help="Path to output metrics JSON report")
    eval_parser.add_argument("--db", type=str, default="data/eval_test.db", help="SQLite database path")

    parsed_args = parser.parse_args()

    if parsed_args.command == "run":
        sys.exit(handle_run(parsed_args))
    elif parsed_args.command == "approve":
        sys.exit(handle_approve(parsed_args))
    elif parsed_args.command == "reject":
        sys.exit(handle_reject(parsed_args))
    elif parsed_args.command == "eval":
        sys.exit(handle_eval(parsed_args))


if __name__ == "__main__":
    main()
