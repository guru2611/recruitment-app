"""
Agent 1 — CV Matcher
Reads CVs and JDs, uses Claude to score each CV against each JD,
copies matches to data/matched/<JD_Title>/, and stores results in DB.
"""

import json
import logging
import shutil
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import anthropic
import pdfplumber

from config import (
    ANTHROPIC_API_KEY, CV_DIR, JD_DIR, MATCHED_DIR, MATCH_THRESHOLD
)
from db.database import get_connection, init_db

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def extract_text_from_pdf(path) -> str:
    try:
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        logger.warning("Could not extract text from %s: %s", path, e)
        return ""


def extract_text_from_file(path) -> str:
    path = str(path)
    if path.lower().endswith(".pdf"):
        return extract_text_from_pdf(path)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return ""


def score_cv_against_jd(cv_text: str, jd_text: str, jd_title: str) -> dict:
    prompt = f"""You are a recruitment specialist. Evaluate how well the candidate's CV matches the job description.

JOB DESCRIPTION ({jd_title}):
{jd_text[:4000]}

CANDIDATE CV:
{cv_text[:4000]}

Respond with ONLY a valid JSON object in this exact format:
{{
  "match": true or false,
  "score": <integer 0-100>,
  "reason": "<brief explanation>"
}}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.error("Claude scoring error: %s", e)
        return {"match": False, "score": 0, "reason": f"Error: {e}"}


def load_jds() -> list[dict]:
    """Load all JDs from the job_descriptions folder and upsert into DB."""
    jds = []
    for jd_file in JD_DIR.iterdir():
        if jd_file.suffix.lower() not in (".pdf", ".txt", ".md"):
            continue
        content = extract_text_from_file(jd_file)
        if not content.strip():
            continue
        title = jd_file.stem.replace("_", " ").replace("-", " ").title()
        folder_path = str(MATCHED_DIR / title)

        with get_connection() as conn:
            existing = conn.execute(
                "SELECT jd_id FROM job_descriptions WHERE title = ?", (title,)
            ).fetchone()
            if existing:
                jd_id = existing["jd_id"]
            else:
                cur = conn.execute(
                    "INSERT INTO job_descriptions (title, content, folder_path) VALUES (?,?,?)",
                    (title, content, folder_path),
                )
                jd_id = cur.lastrowid

        jds.append({"jd_id": jd_id, "title": title, "content": content, "folder_path": folder_path})
    return jds


def run():
    init_db()
    logger.info("Agent 1: Starting CV matching...")

    cv_files = [f for f in CV_DIR.iterdir() if f.suffix.lower() == ".pdf"]
    jds = load_jds()

    if not cv_files:
        logger.warning("No CVs found in %s", CV_DIR)
        return
    if not jds:
        logger.warning("No JDs found in %s", JD_DIR)
        return

    logger.info("Found %d CV(s) and %d JD(s)", len(cv_files), len(jds))

    for cv_path in cv_files:
        cv_text = extract_text_from_pdf(cv_path)
        if not cv_text.strip():
            logger.warning("Empty text from %s, skipping", cv_path.name)
            continue

        # Ensure candidate row exists
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT candidate_id FROM candidates WHERE cv_path = ?", (str(cv_path),)
            ).fetchone()
            if existing:
                candidate_id = existing["candidate_id"]
            else:
                cur = conn.execute(
                    "INSERT INTO candidates (cv_path) VALUES (?)", (str(cv_path),)
                )
                candidate_id = cur.lastrowid

        for jd in jds:
            # Skip if already matched
            with get_connection() as conn:
                already = conn.execute(
                    "SELECT match_id FROM matches WHERE candidate_id=? AND jd_id=?",
                    (candidate_id, jd["jd_id"]),
                ).fetchone()
            if already:
                logger.debug("Already matched %s vs %s, skipping", cv_path.name, jd["title"])
                continue

            logger.info("Scoring %s vs %s...", cv_path.name, jd["title"])
            result = score_cv_against_jd(cv_text, jd["content"], jd["title"])
            score = result.get("score", 0)
            logger.info("  Score: %d | %s", score, result.get("reason", ""))

            with get_connection() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO matches (candidate_id, jd_id, match_score) VALUES (?,?,?)",
                    (candidate_id, jd["jd_id"], score),
                )

            if score >= MATCH_THRESHOLD:
                dest_dir = MATCHED_DIR / jd["title"]
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / cv_path.name
                if not dest.exists():
                    shutil.copy2(str(cv_path), str(dest))
                    logger.info("  Copied %s -> %s", cv_path.name, dest_dir)

    logger.info("Agent 1: CV matching complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
