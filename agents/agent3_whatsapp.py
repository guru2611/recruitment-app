"""
Agent 3 — WhatsApp Notifier
Sends WhatsApp messages to matched candidates who haven't been contacted yet.

NOTE: pywhatkit requires WhatsApp Web to be open and logged in on Chrome.
      This uses sendwhatmsg_instantly() which opens WhatsApp Web automatically.
"""

import logging
import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import TEST_PHONE
from db.database import get_connection, init_db

logger = logging.getLogger(__name__)

WHATSAPP_MESSAGE_TEMPLATE = (
    "Hi {name}! 👋 We reviewed your profile and it looks like a great fit for an "
    "exciting opportunity. You'll shortly receive a call from our AI assistant to "
    "help schedule a convenient interview slot. Please keep your phone handy. "
    "Looking forward to connecting! 🚀"
)

DELAY_BETWEEN_MESSAGES = 20  # seconds


def send_whatsapp(phone: str, message: str) -> bool:
    """
    Send a WhatsApp message by opening Chrome directly via macOS 'open' command
    and using AppleScript to press Enter after the page loads.
    Does NOT use pywhatkit's browser logic (which defaults to Safari).
    """
    import subprocess
    import urllib.parse

    # WhatsApp Web pre-fills phone + message via URL params
    encoded = urllib.parse.quote(message)
    url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded}"

    try:
        # Force open in Chrome (ignores macOS default browser setting)
        subprocess.run(
            ["open", "-a", "Google Chrome", url],
            check=True
        )
        logger.info("  Opened WhatsApp Web in Chrome, waiting 20s for page to load...")
        time.sleep(20)

        # Ask the user to press Enter in Chrome, then confirm here
        print("\n  ✅ Chrome opened with message pre-filled.")
        print("  👉 Click the Send button (or press Enter) in WhatsApp Web.")
        input("  Press Enter HERE once you've sent the message in Chrome... ")
        return True

    except Exception as e:
        logger.error("WhatsApp send failed for %s: %s", phone, e)
        return False


def run():
    init_db()
    logger.info("Agent 3: Starting WhatsApp notifications...")
    logger.warning(
        "IMPORTANT: Ensure WhatsApp Web is open and logged in on Chrome before proceeding."
    )

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.candidate_id, c.name, c.phone
            FROM candidates c
            JOIN communications comm ON comm.candidate_id = c.candidate_id
            WHERE comm.whatsapp_sent = 0
              AND c.phone IS NOT NULL
        """).fetchall()

    if not rows:
        logger.info("No pending WhatsApp notifications.")
        return

    logger.info("Found %d candidate(s) to notify via WhatsApp", len(rows))

    for i, row in enumerate(rows):
        candidate_id = row["candidate_id"]
        name = row["name"] or "there"
        real_phone = row["phone"]

        # Use TEST_PHONE override if set, otherwise use real candidate phone
        phone = TEST_PHONE or real_phone
        if TEST_PHONE:
            logger.info("Sending WhatsApp to %s (override: %s) [candidate_id=%d]", real_phone, phone, candidate_id)
        else:
            logger.info("Sending WhatsApp to %s [candidate_id=%d]", phone, candidate_id)

        message = WHATSAPP_MESSAGE_TEMPLATE.format(name=name)

        success = send_whatsapp(phone, message)

        if success:
            with get_connection() as conn:
                conn.execute(
                    """UPDATE communications
                       SET whatsapp_sent=1, whatsapp_sent_at=CURRENT_TIMESTAMP
                       WHERE candidate_id=?""",
                    (candidate_id,),
                )
            logger.info("  WhatsApp sent successfully to candidate %d", candidate_id)
        else:
            logger.error("  Failed to send WhatsApp to candidate %d", candidate_id)

        # Delay between messages to avoid blocks (skip delay after last message)
        if i < len(rows) - 1:
            logger.info("  Waiting %ds before next message...", DELAY_BETWEEN_MESSAGES)
            time.sleep(DELAY_BETWEEN_MESSAGES)

    logger.info("Agent 3: WhatsApp notifications complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
