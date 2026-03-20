"""
Planner Agent — Orchestrates all 4 agents in sequence.
Checks DB state before each step to avoid re-processing.
"""

import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.database import init_db, get_connection
from config import MATCH_THRESHOLD

logger = logging.getLogger(__name__)


def _has_unmatched_cvs() -> bool:
    """Returns True if there are CVs that haven't been scored against all JDs."""
    with get_connection() as conn:
        jd_count = conn.execute("SELECT COUNT(*) FROM job_descriptions").fetchone()[0]
        if jd_count == 0:
            return False
        # Candidates where the number of match records < number of JDs
        result = conn.execute("""
            SELECT COUNT(*) FROM candidates c
            WHERE (SELECT COUNT(*) FROM matches m WHERE m.candidate_id = c.candidate_id) < ?
        """, (jd_count,)).fetchone()[0]
        return result > 0 or jd_count > 0  # always run agent 1 to pick up new files


def _has_unextracted_candidates() -> bool:
    with get_connection() as conn:
        count = conn.execute("""
            SELECT COUNT(*) FROM candidates c
            JOIN matches m ON m.candidate_id = c.candidate_id
            WHERE m.match_score >= ? AND c.name IS NULL
        """, (MATCH_THRESHOLD,)).fetchone()[0]
        return count > 0


def _has_pending_whatsapp() -> bool:
    with get_connection() as conn:
        count = conn.execute("""
            SELECT COUNT(*) FROM candidates c
            JOIN communications comm ON comm.candidate_id = c.candidate_id
            WHERE comm.whatsapp_sent = 0 AND c.phone IS NOT NULL
        """).fetchone()[0]
        return count > 0


def _has_pending_calls() -> bool:
    with get_connection() as conn:
        count = conn.execute("""
            SELECT COUNT(*) FROM candidates c
            JOIN communications comm ON comm.candidate_id = c.candidate_id
            WHERE comm.whatsapp_sent = 1 AND comm.call_made = 0 AND c.phone IS NOT NULL
        """).fetchone()[0]
        return count > 0


def run_pipeline():
    logger.info("=" * 60)
    logger.info("RECRUITMENT PIPELINE STARTING")
    logger.info("=" * 60)

    init_db()

    # --- Agent 1: CV Matcher ---
    logger.info("\n[Step 1/4] Running CV Matcher...")
    try:
        from agents.agent1_cv_matcher import run as run_agent1
        run_agent1()
        logger.info("[Step 1/4] CV Matcher complete ✓")
    except Exception as e:
        logger.error("[Step 1/4] CV Matcher failed: %s", e)

    # --- Agent 2: Extractor ---
    if _has_unextracted_candidates():
        logger.info("\n[Step 2/4] Running Extractor...")
        try:
            from agents.agent2_extractor import run as run_agent2
            run_agent2()
            logger.info("[Step 2/4] Extractor complete ✓")
        except Exception as e:
            logger.error("[Step 2/4] Extractor failed: %s", e)
    else:
        logger.info("\n[Step 2/4] Extractor: No unprocessed matched candidates — skipping.")

    # --- Agent 3: WhatsApp Notifier ---
    if _has_pending_whatsapp():
        logger.info("\n[Step 3/4] Running WhatsApp Notifier...")
        try:
            from agents.agent3_whatsapp import run as run_agent3
            run_agent3()
            logger.info("[Step 3/4] WhatsApp Notifier complete ✓")
        except Exception as e:
            logger.error("[Step 3/4] WhatsApp Notifier failed: %s", e)
    else:
        logger.info("\n[Step 3/4] WhatsApp Notifier: No pending messages — skipping.")

    # --- Agent 4: AI Caller ---
    if _has_pending_calls():
        logger.info("\n[Step 4/4] Running AI Caller...")
        try:
            from agents.agent4_caller import run as run_agent4
            run_agent4()
            logger.info("[Step 4/4] AI Caller complete ✓")
        except Exception as e:
            logger.error("[Step 4/4] AI Caller failed: %s", e)
    else:
        logger.info("\n[Step 4/4] AI Caller: No pending calls — skipping.")

    logger.info("\n" + "=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
