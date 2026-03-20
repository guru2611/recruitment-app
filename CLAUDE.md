# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multi-agent AI recruitment automation system that screens CVs, matches them to job descriptions, contacts candidates, and schedules interviews via AI phone calls.

## Commands

```bash
# Start dashboard (primary interface) — run from recruitment_app/
streamlit run dashboard.py

# First-time DB setup (adds interview_status, interview_feedback, interview_date, rating columns)
python db/migrate.py

# CLI pipeline
python main.py                # Full pipeline
python main.py --agent 1      # CV Matcher only
python main.py --agent 2      # Extractor only
python main.py --agent 3      # WhatsApp only
python main.py --agent 4      # Bolna caller only
python main.py --poll         # Poll Bolna for completed calls, extract slot, send invite
python main.py --status       # Rich CLI status table

# Clear all tables
python3 -c "
import sys; sys.path.insert(0, '.')
from db.database import get_connection, init_db
init_db()
with get_connection() as conn:
    conn.execute('DELETE FROM communications')
    conn.execute('DELETE FROM matches')
    conn.execute('DELETE FROM candidates')
    conn.execute('DELETE FROM job_descriptions')
"
```

## Architecture & Key Decisions

**Pipeline flow:**
1. Agent 1 — scores every CV×JD pair via `claude-opus-4-6`, copies matches (≥70) to `data/matched/`. If no match, pipeline stops and shows a "Not a Match" card in the dashboard (no further agents run).
2. Agent 2 — extracts name/phone/email from matched CVs via `claude-opus-4-6`; also creates the `communications` row for each matched candidate.
3. Agent 3 — **disabled in dashboard**. `whatsapp_sent` is auto-set to 1 so Agent 4 proceeds. The underlying agent opens Chrome with a pre-filled WhatsApp Web URL (manual send) when run via CLI.
4. Agent 4 — queues Bolna outbound call, saves `execution_id`, **does NOT send invite yet**
5. Poll (`--poll` or "🔄 Check Call Results" button in Interview Feedback page) — fetches Bolna execution, parses chosen slot from transcript, saves to `candidates.interview_date`, sends `.ics` invite via Gmail SMTP

**Dashboard pages:** Upload CV · Overview · Job Descriptions · Candidates · Interview Feedback · Match Scores · Architecture. All pages are in `dashboard.py` as `elif page == "..."` blocks. The sidebar uses `st.radio` for navigation.

**Idempotency:** `planner_agent.py` checks DB state before each step and skips agents where work is already complete. Re-running the full pipeline is safe — already-matched CVs, extracted candidates, and queued calls are not re-processed.

**No-match handling:** After Agent 1, the dashboard checks `matches WHERE match_score >= 70`. If none, all remaining agents are marked skipped and a styled "Not a Match" card is shown. Balloons/success only fire when the CV matched.

**Invite timing:** Invite is sent only after polling Bolna post-call — never at call-queue time. The slot is parsed from the transcript using regex (JSON block or natural language confirmation fallback). `generate_ics` expects slot strings in the format produced by `INTERVIEW_SLOTS` in `config.py` (e.g. `"Monday, March 25, 2026 at 10:00 AM IST"`).

**Env loading:** `dashboard.py` loads `.env` using direct `os.environ[k] = v` assignment (always overwrites, needed because Streamlit changes CWD). `main.py` uses `os.environ.setdefault` (won't override already-set env vars). Both locate `.env` via `os.path.abspath(__file__)` — always use absolute path.

**TEST_PHONE / TEST_EMAIL:** Optional overrides in `.env`. When set, all calls and invites go to these values instead of real candidate data. Pattern: `TEST_PHONE or real_phone` / `TEST_EMAIL or candidate.email`.

**Bolna API:** `POST https://api.bolna.ai/call` (not `.dev`). Returns `execution_id`. Poll via `GET https://api.bolna.ai/executions/{execution_id}`. Passes `first_name` (split from full name) in `user_data` — must be referenced as `{{first_name}}` in the Bolna agent prompt to greet candidates by first name.

**WhatsApp:** Agent 3 bypasses pywhatkit entirely. Uses `subprocess.run(["open", "-a", "Google Chrome", url])` with a pre-filled WhatsApp Web URL. Requires manual send in browser. Disabled in dashboard UI.

## Database

SQLite at `db/recruitment.db`. Base schema is in `db/database.py:init_db()`; extra columns are added by `db/migrate.py` (run once after first init).

Tables:
- `candidates` — cv_path, name, phone, email, status, interview_status, interview_feedback, interview_date, rating
- `job_descriptions` — title, content, folder_path
- `matches` — candidate_id, jd_id, match_score
- `communications` — whatsapp_sent, call_made, invite_sent, bolna_execution_id (with timestamps)

> **Note:** `bolna_execution_id` and the interview columns on `candidates` are not in the base `init_db()` schema — they are added by `db/migrate.py`. Run migrate before using Agent 4 or the Interview Feedback dashboard page.
