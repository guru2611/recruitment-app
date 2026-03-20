#!/usr/bin/env python3
"""
Recruitment Pipeline — Entry Point

Usage:
  python main.py              # Run full pipeline
  python main.py --agent 1   # Run only Agent 1 (CV Matcher)
  python main.py --agent 2   # Run only Agent 2 (Extractor)
  python main.py --agent 3   # Run only Agent 3 (WhatsApp Notifier)
  python main.py --agent 4   # Run only Agent 4 (AI Caller)
  python main.py --poll      # Poll Bolna for completed calls, save interview slots
  python main.py --status    # Show pipeline status dashboard
"""

import argparse
import logging
import sys
import os

# Ensure recruitment_app is on path when running as python main.py
sys.path.insert(0, os.path.dirname(__file__))

# Load .env file from same directory as main.py
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.split("#")[0].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))

_load_env()

from db.database import init_db, get_connection

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(__file__), "pipeline.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


# ── Rich dashboard ─────────────────────────────────────────────────────────────
def show_status():
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        console = Console()
        init_db()

        with get_connection() as conn:
            total_cvs = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
            total_jds = conn.execute("SELECT COUNT(*) FROM job_descriptions").fetchone()[0]
            total_matches = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
            extracted = conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE name IS NOT NULL"
            ).fetchone()[0]
            wa_sent = conn.execute(
                "SELECT COUNT(*) FROM communications WHERE whatsapp_sent=1"
            ).fetchone()[0]
            calls_made = conn.execute(
                "SELECT COUNT(*) FROM communications WHERE call_made=1"
            ).fetchone()[0]
            invites_sent = conn.execute(
                "SELECT COUNT(*) FROM communications WHERE invite_sent=1"
            ).fetchone()[0]

        console.print("\n[bold cyan]Recruitment Pipeline — Status Dashboard[/bold cyan]\n")

        summary = Table(box=box.ROUNDED, show_header=False)
        summary.add_column("Metric", style="bold")
        summary.add_column("Value", style="green")
        summary.add_row("CVs loaded", str(total_cvs))
        summary.add_row("Job Descriptions", str(total_jds))
        summary.add_row("Total matches scored", str(total_matches))
        summary.add_row("Candidates extracted", str(extracted))
        summary.add_row("WhatsApp sent", str(wa_sent))
        summary.add_row("Calls initiated", str(calls_made))
        summary.add_row("Calendar invites sent", str(invites_sent))
        console.print(summary)

        # Candidate details
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT c.candidate_id, c.name, c.phone, c.status,
                       COALESCE(comm.whatsapp_sent, 0) AS wa,
                       COALESCE(comm.call_made, 0) AS call,
                       COALESCE(comm.invite_sent, 0) AS invite,
                       MAX(m.match_score) AS top_score
                FROM candidates c
                LEFT JOIN communications comm ON comm.candidate_id = c.candidate_id
                LEFT JOIN matches m ON m.candidate_id = c.candidate_id
                GROUP BY c.candidate_id
                ORDER BY top_score DESC
            """).fetchall()

        if rows:
            console.print("\n[bold]Candidate Details[/bold]")
            tbl = Table(box=box.SIMPLE_HEAVY)
            tbl.add_column("ID")
            tbl.add_column("Name")
            tbl.add_column("Phone")
            tbl.add_column("Top Score")
            tbl.add_column("WhatsApp")
            tbl.add_column("Call")
            tbl.add_column("Invite")
            for r in rows:
                tbl.add_row(
                    str(r["candidate_id"]),
                    r["name"] or "[dim]—[/dim]",
                    r["phone"] or "[dim]—[/dim]",
                    str(r["top_score"] or "—"),
                    "✓" if r["wa"] else "✗",
                    "✓" if r["call"] else "✗",
                    "✓" if r["invite"] else "✗",
                )
            console.print(tbl)
        console.print()

    except ImportError:
        # Fallback if rich is not installed
        logger.info("Install 'rich' for a better dashboard. Showing plain output:")
        init_db()
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM candidates").fetchall()
            for r in rows:
                logger.info(dict(r))


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Recruitment Pipeline")
    parser.add_argument(
        "--agent", type=int, choices=[1, 2, 3, 4],
        help="Run a specific agent (1=Matcher, 2=Extractor, 3=WhatsApp, 4=Caller)"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show pipeline status dashboard"
    )
    parser.add_argument(
        "--poll", action="store_true",
        help="Poll Bolna for completed calls and save chosen interview slots"
    )
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.poll:
        init_db()
        from agents.agent4_caller import poll_call_results
        poll_call_results()
        return

    if args.agent:
        init_db()
        agent_map = {
            1: ("agents.agent1_cv_matcher", "CV Matcher"),
            2: ("agents.agent2_extractor", "Extractor"),
            3: ("agents.agent3_whatsapp", "WhatsApp Notifier"),
            4: ("agents.agent4_caller", "AI Caller"),
        }
        module_path, name = agent_map[args.agent]
        logger.info("Running Agent %d: %s", args.agent, name)
        import importlib
        mod = importlib.import_module(module_path)
        mod.run()
    else:
        # Full pipeline
        from agents.planner_agent import run_pipeline
        run_pipeline()
        show_status()


if __name__ == "__main__":
    main()
