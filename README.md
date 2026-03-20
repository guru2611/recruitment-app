# Recruitment Automation Pipeline

A multi-agent AI system that automatically screens CVs, matches them to job descriptions, and schedules interviews via AI phone calls.

## Architecture

```
main.py  →  planner_agent.py
                ├── agent1_cv_matcher.py   (Claude API — match CVs to JDs)
                ├── agent2_extractor.py    (Claude API — extract name/phone/email)
                ├── agent3_whatsapp.py     (WhatsApp Web via Chrome — manual send, disabled in dashboard)
                └── agent4_caller.py      (Bolna.ai — outbound AI call → poll → .ics invite)
```

All state is persisted in a local SQLite database (`db/recruitment.db`). Agents are idempotent — re-running the pipeline skips already-processed candidates.

## Setup

### 1. Install dependencies

```bash
cd recruitment_app
pip install -r requirements.txt
```

### 2. Configure environment

Create `.env` in the repo root (next to `recruitment_app/`):

```bash
ANTHROPIC_API_KEY=sk-ant-...
BOLNA_API_KEY=...
BOLNA_AGENT_ID=...
SMTP_USER=your@gmail.com
SMTP_PASS=your_gmail_app_password    # Gmail App Password — not your main password

# Optional: override all calls/invites to a single number/email during testing
# Remove these to use real candidate phone/email extracted from the CV
TEST_PHONE=+91XXXXXXXXXX
TEST_EMAIL=test@example.com
```

### 3. Add data

- Drop candidate CVs (PDF) into `data/cvs/`
- Drop job description files (PDF or TXT) into `data/job_descriptions/`

### 4. Configure Bolna.ai

1. Sign up at https://app.bolna.ai
2. Create an agent that offers interview slots to candidates
3. In your agent's prompt, use `{{first_name}}` to greet candidates by first name
4. Connect a Plivo phone number to the agent (required for outbound calls)
5. Copy `BOLNA_API_KEY` and `BOLNA_AGENT_ID` into `.env`

## Running

### Dashboard (recommended)

```bash
cd recruitment_app
streamlit run dashboard.py
```

Upload a CV from the **Upload CV** tab — the pipeline runs automatically.

| Tab | Description |
|-----|-------------|
| 📤 Upload CV | Upload a PDF CV and run the full pipeline |
| 📊 Overview | Metrics, funnel chart, and interview status breakdown |
| 💼 Job Descriptions | Browse loaded JDs with applicant and match counts |
| 👥 Candidates | Cards for all matched candidates with contact and status info |
| ✍️ Interview Feedback | Poll Bolna call results, update status, add notes and ratings |
| 📈 Match Scores | All CV×JD scores with match/no-match badges |
| 🏗 Architecture | System architecture diagram |

### CLI

```bash
python main.py                # Full pipeline
python main.py --agent 1      # CV Matcher only
python main.py --agent 2      # Extractor only
python main.py --agent 3      # WhatsApp only
python main.py --agent 4      # Bolna caller only
python main.py --poll         # Poll Bolna for completed calls → extract slot → send invite
python main.py --status       # Status summary table
```

## Pipeline Flow

| Step | Agent | What it does |
|------|-------|-------------|
| 1 | CV Matcher | Scores each CV against each JD using Claude. Copies matches (score ≥ 70) to `data/matched/<JD>/`. If no match, pipeline stops and shows a "Not a Match" card. |
| 2 | Extractor | Extracts name, phone, email from matched CVs using Claude |
| 3 | WhatsApp | Disabled in dashboard (auto-marked sent). Via CLI: opens WhatsApp Web in Chrome with pre-filled message — send manually in browser |
| 4 | AI Caller | Queues outbound AI call via Bolna.ai. Saves `execution_id` — no invite yet |
| Poll | — | Polls Bolna after call completes, extracts chosen slot from transcript, sends `.ics` calendar invite |

## After the Call

Once a candidate completes the Bolna call and selects an interview slot:

1. Go to dashboard → **Interview Feedback** page
2. Click **🔄 Check Call Results**
3. The system polls Bolna, extracts the chosen slot, saves it to the DB, and sends a calendar invite via Gmail SMTP

## Database Tables

- `candidates` — CV path, name, phone, email, interview status, interview date, feedback, rating
- `job_descriptions` — Title, content, folder path
- `matches` — candidate ↔ JD match scores
- `communications` — WhatsApp sent, call made, invite sent, Bolna execution ID (with timestamps)

## Notes

- `TEST_PHONE` and `TEST_EMAIL` are optional. When set, all calls and invites go to these values. When removed from `.env`, the system uses the real candidate phone/email extracted from their CV.
- Match threshold defaults to 70, configurable via `MATCH_THRESHOLD` env var.
- One failed candidate never stops the pipeline — errors are logged and processing continues.
- Pipeline logs go to `pipeline.log` and stdout.
