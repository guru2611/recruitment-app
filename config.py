import os

# === TEST OVERRIDES (used in place of real candidate data during testing) ===
TEST_PHONE = os.getenv("TEST_PHONE")   # If set, overrides all candidate phones
TEST_EMAIL = os.getenv("TEST_EMAIL")   # If set, overrides all candidate emails

# === API KEYS ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BOLNA_API_KEY = os.getenv("BOLNA_API_KEY", "")
BOLNA_AGENT_ID = os.getenv("BOLNA_AGENT_ID", "")

# === EMAIL / SMTP ===
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# === PIPELINE SETTINGS ===
MATCH_THRESHOLD = int(os.getenv("MATCH_THRESHOLD", "70"))

# === PATHS ===
import pathlib
BASE_DIR = pathlib.Path(__file__).parent
CV_DIR = BASE_DIR / "data" / "cvs"
JD_DIR = BASE_DIR / "data" / "job_descriptions"
MATCHED_DIR = BASE_DIR / "data" / "matched"
DB_PATH = BASE_DIR / "db" / "recruitment.db"

# === SAMPLE INTERVIEW SLOTS (hardcoded for testing) ===
INTERVIEW_SLOTS = [
    "Monday, March 25, 2026 at 10:00 AM IST",
    "Tuesday, March 26, 2026 at 2:00 PM IST",
    "Wednesday, March 27, 2026 at 11:00 AM IST",
]
