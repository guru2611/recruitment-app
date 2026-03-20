"""
Agent 4 — AI Caller
Uses Bolna.ai to initiate outbound AI calls to candidates who received a WhatsApp message.
After a call, sends a .ics calendar invite via email.
Polls completed calls to extract the interview slot chosen by the candidate.
"""

import json
import logging
import re
import smtplib
import sys
import os
import time
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    BOLNA_API_KEY, BOLNA_AGENT_ID,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
    TEST_PHONE, TEST_EMAIL, INTERVIEW_SLOTS,
)
from db.database import get_connection, init_db

logger = logging.getLogger(__name__)

BOLNA_CALL_URL  = "https://api.bolna.ai/call"
BOLNA_EXEC_URL  = "https://api.bolna.ai/executions/{execution_id}"


def initiate_bolna_call(phone: str, candidate_name: str) -> str | None:
    """
    Initiate an outbound AI call via Bolna.ai.
    Returns the execution_id on success, None on failure.
    """
    if not BOLNA_API_KEY or not BOLNA_AGENT_ID:
        logger.warning("BOLNA_API_KEY or BOLNA_AGENT_ID not set — skipping call.")
        return None

    first_name = candidate_name.split()[0] if candidate_name else "there"
    slots_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(INTERVIEW_SLOTS))
    payload = {
        "agent_id": BOLNA_AGENT_ID,
        "recipient_phone_number": phone,
        "user_data": {
            "candidate_name": candidate_name,
            "first_name": first_name,
            "interview_slots": INTERVIEW_SLOTS,
            "slots_text": slots_text,
        },
    }
    headers = {
        "Authorization": f"Bearer {BOLNA_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(BOLNA_CALL_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        execution_id = data.get("execution_id") or data.get("run_id")
        logger.info("Bolna call initiated. execution_id=%s", execution_id)
        return execution_id
    except requests.HTTPError as e:
        logger.error("Bolna API HTTP error: %s — %s", e, e.response.text if e.response else "")
        return None
    except Exception as e:
        logger.error("Bolna call error: %s", e)
        return None


def fetch_execution(execution_id: str) -> dict | None:
    """Fetch a Bolna execution by ID."""
    try:
        resp = requests.get(
            BOLNA_EXEC_URL.format(execution_id=execution_id),
            headers={"Authorization": f"Bearer {BOLNA_API_KEY}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Failed to fetch execution %s: %s", execution_id, e)
        return None


def extract_slot_from_transcript(transcript: str) -> str | None:
    """
    Parse the interview slot the candidate chose from the Bolna transcript.
    Tries JSON block first, then natural language confirmation lines.
    """
    if not transcript:
        return None

    # 1. Try JSON block: {"interview_date": "...", "interview_slot": "..."}
    json_matches = re.findall(r'\{[^{}]*"interview_date"[^{}]*\}', transcript, re.DOTALL)
    if json_matches:
        try:
            data = json.loads(json_matches[-1])
            date = data.get("interview_date", "")
            slot = data.get("interview_slot", "")
            if date and slot:
                return f"{date} {slot}"
        except json.JSONDecodeError:
            pass

    # 2. Natural language: "chosen the interview slot on <day> from <time>"
    nl_match = re.search(
        r'chosen the interview slot on ([A-Za-z]+) from ([\d]+ [AP]M to [\d]+ [AP]M)',
        transcript, re.IGNORECASE
    )
    if nl_match:
        return f"{nl_match.group(1)} {nl_match.group(2)}"

    # 3. Broader: "slot on <day> from <time>"
    broad_match = re.search(
        r'slot on ([A-Za-z]+) from ([\d:\s]+[AP]M to [\d:\s]+[AP]M)',
        transcript, re.IGNORECASE
    )
    if broad_match:
        return f"{broad_match.group(1)} {broad_match.group(2)}"

    return None


def poll_call_results():
    """
    Check all completed Bolna calls and save the chosen interview slot
    to the candidates table (interview_date + interview_status).
    """
    if not BOLNA_API_KEY:
        logger.warning("BOLNA_API_KEY not set — skipping poll.")
        return

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.candidate_id, c.name, c.email, comm.bolna_execution_id
            FROM candidates c
            JOIN communications comm ON comm.candidate_id = c.candidate_id
            WHERE comm.call_made = 1
              AND comm.bolna_execution_id IS NOT NULL
              AND (c.interview_status IS NULL OR c.interview_status = 'Pending')
        """).fetchall()

    if not rows:
        logger.info("No pending call results to poll.")
        return

    logger.info("Polling %d call result(s)...", len(rows))

    for row in rows:
        candidate_id  = row["candidate_id"]
        name          = row["name"]
        email         = row["email"]
        execution_id  = row["bolna_execution_id"]

        data = fetch_execution(execution_id)
        if not data:
            continue

        status = data.get("status")
        logger.info("Execution %s status: %s", execution_id, status)

        if status not in ("completed", "call-disconnected"):
            continue

        # Try extracted_data first, then parse transcript
        slot = None
        extracted = data.get("extracted_data") or data.get("custom_extractions")
        if extracted and isinstance(extracted, dict):
            date = extracted.get("interview_date", "")
            s    = extracted.get("interview_slot", "")
            if date and s:
                slot = f"{date} {s}"

        if not slot:
            slot = extract_slot_from_transcript(data.get("transcript", ""))

        if slot:
            with get_connection() as conn:
                conn.execute(
                    """UPDATE candidates
                       SET interview_date=?, interview_status='Scheduled'
                       WHERE candidate_id=?""",
                    (slot, candidate_id),
                )
            logger.info("  Saved slot '%s' for %s (id=%d)", slot, name, candidate_id)

            # Send invite to TEST_EMAIL override if set, else to candidate's real email
            invite_to = TEST_EMAIL or email
            if not invite_to:
                logger.warning("  No email for candidate %d — skipping invite", candidate_id)
                continue
            invite_ok = send_calendar_invite(name, slot, invite_to)
            if invite_ok:
                with get_connection() as conn:
                    conn.execute(
                        """UPDATE communications
                           SET invite_sent=1, invite_sent_at=CURRENT_TIMESTAMP
                           WHERE candidate_id=?""",
                        (candidate_id,),
                    )
                logger.info("  Calendar invite sent to %s for slot: %s", invite_to, slot)
        else:
            logger.warning("  Could not extract slot for %s (id=%d) — invite not sent", name, candidate_id)


def generate_ics(candidate_name: str, slot_str: str) -> str:
    """Generate a minimal .ics calendar invite string."""
    try:
        slot_clean = slot_str.replace(" IST", "").replace(" at ", " ")
        dt = datetime.strptime(slot_clean, "%A, %B %d, %Y %I:%M %p")
    except Exception:
        dt = datetime.utcnow() + timedelta(hours=24)

    dt_end = dt + timedelta(hours=1)
    fmt = "%Y%m%dT%H%M%SZ"
    uid = str(uuid.uuid4())
    now = datetime.utcnow().strftime(fmt)

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//RecruitBot//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{now}
DTSTART:{dt.strftime(fmt)}
DTEND:{dt_end.strftime(fmt)}
SUMMARY:Interview — {candidate_name}
DESCRIPTION:Interview scheduled via AI recruitment assistant.\\nSlot: {slot_str}
ORGANIZER:mailto:{SMTP_USER or TEST_EMAIL}
ATTENDEE:mailto:{TEST_EMAIL}
STATUS:CONFIRMED
BEGIN:VALARM
TRIGGER:-PT30M
ACTION:DISPLAY
DESCRIPTION:Interview reminder
END:VALARM
END:VEVENT
END:VCALENDAR"""
    return ics


def send_calendar_invite(candidate_name: str, slot_str: str, to_email: str) -> bool:
    """Send a .ics calendar invite via email."""
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP credentials not set — skipping email invite.")
        return False

    ics_content = generate_ics(candidate_name, slot_str)

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = f"Interview Scheduled — {candidate_name}"

    body = (
        f"Hi,\n\nYour interview has been scheduled.\n\n"
        f"Candidate: {candidate_name}\nSlot: {slot_str}\n\n"
        f"Please find the calendar invite attached.\n\nBest regards,\nRecruitBot"
    )
    msg.attach(MIMEText(body, "plain"))

    ics_part = MIMEBase("text", "calendar", method="REQUEST", name="invite.ics")
    ics_part.set_payload(ics_content.encode("utf-8"))
    encoders.encode_base64(ics_part)
    ics_part.add_header("Content-Disposition", "attachment", filename="invite.ics")
    msg.attach(ics_part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        logger.info("Calendar invite sent to %s", to_email)
        return True
    except Exception as e:
        logger.error("Failed to send email invite: %s", e)
        return False


def run():
    init_db()
    logger.info("Agent 4: Starting AI caller pipeline...")

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.candidate_id, c.name, c.phone, c.email
            FROM candidates c
            JOIN communications comm ON comm.candidate_id = c.candidate_id
            WHERE comm.whatsapp_sent = 1
              AND comm.call_made = 0
              AND c.phone IS NOT NULL
        """).fetchall()

    if not rows:
        logger.info("No candidates pending a call.")
        return

    logger.info("Found %d candidate(s) to call", len(rows))

    for row in rows:
        candidate_id = row["candidate_id"]
        name         = row["name"] or "Candidate"
        real_phone   = row["phone"]

        # Use TEST_PHONE override if set, otherwise use real candidate phone
        phone = TEST_PHONE or real_phone
        if TEST_PHONE:
            logger.info("Calling %s (override: %s) [candidate_id=%d]", real_phone, phone, candidate_id)
        else:
            logger.info("Calling %s [candidate_id=%d]", phone, candidate_id)

        execution_id = initiate_bolna_call(phone, name)

        if execution_id:
            with get_connection() as conn:
                conn.execute(
                    """UPDATE communications
                       SET call_made=1, call_made_at=CURRENT_TIMESTAMP,
                           bolna_execution_id=?
                       WHERE candidate_id=?""",
                    (execution_id, candidate_id),
                )
            logger.info(
                "  Call queued for candidate %d (execution_id=%s) — invite will be sent after call completes",
                candidate_id, execution_id
            )
        else:
            logger.error("  Call failed for candidate %d", candidate_id)

    logger.info("Agent 4: Caller pipeline complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
