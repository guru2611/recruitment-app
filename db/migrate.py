"""Add interview feedback columns to candidates table."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.database import get_connection, init_db

init_db()
with get_connection() as conn:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(candidates)").fetchall()]
    if "interview_status" not in cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN interview_status TEXT DEFAULT 'Pending'")
    if "interview_feedback" not in cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN interview_feedback TEXT")
    if "interview_date" not in cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN interview_date TEXT")
    if "rating" not in cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN rating INTEGER")
print("Migration complete.")
