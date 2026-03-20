"""
Agent 2 — Extractor
For all matched CVs (score >= threshold), extract name, phone, email using Claude.
"""

import json
import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import anthropic
import pdfplumber

from config import ANTHROPIC_API_KEY, MATCH_THRESHOLD
from db.database import get_connection, init_db

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def extract_pdf_text(cv_path: str) -> str:
    try:
        with pdfplumber.open(cv_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        logger.warning("Cannot read %s: %s", cv_path, e)
        return ""


def extract_candidate_info(cv_text: str) -> dict:
    prompt = f"""Extract contact information from this CV text.

CV TEXT:
{cv_text[:5000]}

Respond ONLY with a valid JSON object:
{{
  "name": "<full name or null>",
  "phone": "<phone with country code if available, or null>",
  "email": "<email address or null>"
}}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.error("Extraction error: %s", e)
        return {"name": None, "phone": None, "email": None}


def run():
    init_db()
    logger.info("Agent 2: Starting candidate extraction...")

    with get_connection() as conn:
        # Get candidates that have at least one match >= threshold but no name extracted yet
        rows = conn.execute("""
            SELECT DISTINCT c.candidate_id, c.cv_path, c.name
            FROM candidates c
            JOIN matches m ON m.candidate_id = c.candidate_id
            WHERE m.match_score >= ?
              AND c.name IS NULL
        """, (MATCH_THRESHOLD,)).fetchall()

    if not rows:
        logger.info("No unprocessed matched candidates found.")
        return

    logger.info("Found %d candidate(s) to process", len(rows))

    for row in rows:
        candidate_id = row["candidate_id"]
        cv_path = row["cv_path"]
        logger.info("Extracting info from: %s", cv_path)

        try:
            cv_text = extract_pdf_text(cv_path)
            if not cv_text.strip():
                logger.warning("Empty CV text for candidate %d, skipping", candidate_id)
                continue

            info = extract_candidate_info(cv_text)
            name = info.get("name")
            phone = info.get("phone")
            email = info.get("email")

            logger.info("  Name: %s | Phone: %s | Email: %s", name, phone, email)

            with get_connection() as conn:
                conn.execute(
                    """UPDATE candidates
                       SET name=?, phone=?, email=?, status='extracted'
                       WHERE candidate_id=?""",
                    (name, phone, email, candidate_id),
                )
                # Ensure communications row exists
                conn.execute(
                    "INSERT OR IGNORE INTO communications (candidate_id) VALUES (?)",
                    (candidate_id,),
                )
        except Exception as e:
            logger.error("Failed processing candidate %d: %s", candidate_id, e)

    logger.info("Agent 2: Extraction complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
