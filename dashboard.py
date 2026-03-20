"""
Recruitment Pipeline Dashboard — Streamlit App
Run: streamlit run dashboard.py
"""

import logging
import os
import sys
import time
import subprocess
import urllib.parse
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
from datetime import datetime

from config import CV_DIR, INTERVIEW_SLOTS, TEST_EMAIL, BASE_DIR
from db.database import get_connection, init_db

# ── Load env ───────────────────────────────────────────────────────────────────
def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.split("#")[0].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"')

load_env()
init_db()

# Pre-load JDs from disk into DB on startup
try:
    from agents.agent1_cv_matcher import load_jds as _load_jds
    _load_jds()
except Exception:
    pass

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Recruitment Pipeline", page_icon="🎯", layout="wide")

st.markdown("""
<style>
.metric-card {
    background:#f8fafc; border:1px solid #e2e8f0;
    border-radius:12px; padding:20px; text-align:center;
    display:flex; flex-direction:column; align-items:center;
    justify-content:center; height:140px; box-sizing:border-box;
}
.metric-value { font-size:2.2rem; font-weight:700; color:#1e40af; line-height:1.1; }
.metric-label { font-size:0.85rem; color:#64748b; margin-top:6px; line-height:1.3; }
.status-pill {
    display:inline-block; padding:3px 10px;
    border-radius:20px; font-size:0.78rem; font-weight:600;
}
.agent-row {
    display:flex; align-items:center; gap:12px;
    padding:10px 14px; border-radius:8px;
    margin-bottom:8px; background:#f8fafc;
    border:1px solid #e2e8f0; font-size:0.95rem;
    color:#1e293b !important;
}
.agent-row b { color:#0f172a !important; }
.agent-row span { color:#475569 !important; }
.log-box {
    background:#0f172a; color:#94a3b8; font-family:monospace;
    font-size:0.78rem; padding:12px; border-radius:8px;
    max-height:260px; overflow-y:auto; white-space:pre-wrap;
}
</style>
""", unsafe_allow_html=True)

# ── Data helpers ───────────────────────────────────────────────────────────────
def get_metrics():
    with get_connection() as conn:
        return {
            "cvs":     conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
            "jds":     conn.execute("SELECT COUNT(*) FROM job_descriptions").fetchone()[0],
            "matched": conn.execute("SELECT COUNT(DISTINCT candidate_id) FROM matches WHERE match_score >= 70").fetchone()[0],
            "wa":      conn.execute("SELECT COUNT(*) FROM communications WHERE whatsapp_sent=1").fetchone()[0],
            "calls":   conn.execute("SELECT COUNT(*) FROM communications WHERE call_made=1").fetchone()[0],
            "invites": conn.execute("SELECT COUNT(*) FROM communications WHERE invite_sent=1").fetchone()[0],
        }

def get_candidates():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.candidate_id, c.name, c.phone, c.email,
                   c.interview_status, c.interview_feedback, c.interview_date, c.rating,
                   COALESCE(MAX(m.match_score), 0) AS top_score,
                   GROUP_CONCAT(jd.title, ', ')    AS matched_jds,
                   COALESCE(comm.whatsapp_sent, 0) AS whatsapp_sent,
                   COALESCE(comm.call_made, 0)     AS call_made,
                   COALESCE(comm.invite_sent, 0)   AS invite_sent
            FROM candidates c
            JOIN matches m ON m.candidate_id = c.candidate_id AND m.match_score >= 70
            LEFT JOIN job_descriptions jd ON jd.jd_id = m.jd_id
            LEFT JOIN communications comm ON comm.candidate_id = c.candidate_id
            GROUP BY c.candidate_id ORDER BY top_score DESC
        """).fetchall()
        return [dict(r) for r in rows]

def update_feedback(candidate_id, status, feedback, interview_date, rating):
    with get_connection() as conn:
        conn.execute("""
            UPDATE candidates SET interview_status=?, interview_feedback=?,
            interview_date=?, rating=? WHERE candidate_id=?
        """, (status, feedback, interview_date, rating, candidate_id))

def get_job_descriptions():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT jd.jd_id, jd.title, jd.content, jd.created_at,
                   COUNT(m.candidate_id) AS total_applicants,
                   SUM(CASE WHEN m.match_score >= 70 THEN 1 ELSE 0 END) AS matched
            FROM job_descriptions jd
            LEFT JOIN matches m ON m.jd_id = jd.jd_id
            GROUP BY jd.jd_id
            ORDER BY jd.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

def get_all_scores():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.name, jd.title, m.match_score FROM matches m
            JOIN candidates c ON c.candidate_id = m.candidate_id
            JOIN job_descriptions jd ON jd.jd_id = m.jd_id
            ORDER BY m.match_score DESC
        """).fetchall()
        return [dict(r) for r in rows]

# ── Logging capture helper ─────────────────────────────────────────────────────
class ListHandler(logging.Handler):
    def __init__(self, log_list):
        super().__init__()
        self.log_list = log_list
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.log_list.append(self.format(record))

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")
    st.image(logo_path, width=60)
    st.title("Recruitment AI")
    page = st.radio("Navigate", [
        "📤 Upload CV",
        "📊 Overview",
        "💼 Job Descriptions",
        "👥 Candidates",
        "✍️ Interview Feedback",
        "📈 Match Scores",
        "🏗 Architecture",
    ], label_visibility="collapsed")
    st.divider()
    if st.button("🔄 Refresh"):
        st.experimental_rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Upload CV
# ══════════════════════════════════════════════════════════════════════════════
if page == "📤 Upload CV":
    st.title("📤 Upload CV & Run Pipeline")
    st.caption("Upload a candidate CV — the pipeline will run automatically.")

    uploaded = st.file_uploader("Drop a PDF CV here", type=["pdf"], label_visibility="collapsed")

    if uploaded:
        save_path = CV_DIR / uploaded.name
        st.success(f"📄 **{uploaded.name}** ready to process.")
        if st.button("🚀 Run Pipeline", type="primary", use_container_width=True):

            # Save file (overwrite if exists)
            CV_DIR.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(uploaded.getbuffer())

                st.divider()
                st.subheader("Pipeline Progress")

                # ── Agent status placeholders ──────────────────────────────
                AGENTS = [
                    (1, "CV Matcher",   "Scoring CV against all Job Descriptions"),
                    (2, "Extractor",    "Extracting name, phone & email from CV"),
                    (3, "WhatsApp",     "Sending WhatsApp notification"),
                    (4, "AI Caller",    "Initiating Bolna call + calendar invite"),
                ]

                status_slots = {}
                for num, name, desc in AGENTS:
                    status_slots[num] = st.empty()
                    status_slots[num].markdown(
                        f"<div class='agent-row'>⏸ <b>Agent {num}: {name}</b> — <span style='color:#94a3b8'>{desc}</span></div>",
                        unsafe_allow_html=True,
                    )

                st.divider()
                log_header = st.empty()
                log_box    = st.empty()
                wa_section = st.empty()   # placeholder for WhatsApp manual step

                logs = []
                handler = ListHandler(logs)
                root_logger = logging.getLogger()
                root_logger.addHandler(handler)

                def refresh_logs():
                    log_header.markdown("**📋 Live Log**")
                    log_box.markdown(
                        f"<div class='log-box'>" + "\n".join(logs[-40:]) + "</div>",
                        unsafe_allow_html=True,
                    )

                def set_agent(num, name, state, detail="", color="#1e40af"):
                    icons = {"running": "🔄", "done": "✅", "failed": "❌", "skipped": "⏭"}
                    icon = icons.get(state, "⏸")
                    bg   = {"running": "#eff6ff", "done": "#f0fdf4", "failed": "#fef2f2", "skipped": "#f8fafc"}.get(state, "#f8fafc")
                    border = {"running": "#3b82f6", "done": "#10b981", "failed": "#ef4444", "skipped": "#e2e8f0"}.get(state, "#e2e8f0")
                    status_slots[num].markdown(
                        f"<div class='agent-row' style='background:{bg};border-color:{border}'>"
                        f"{icon} <b>Agent {num}: {name}</b>"
                        + (f" — <span style='color:#64748b'>{detail}</span>" if detail else "")
                        + "</div>",
                        unsafe_allow_html=True,
                    )

                # ── Agent 1: CV Matcher ───────────────────────────────────
                set_agent(1, "CV Matcher", "running", "Scoring with Claude...")
                try:
                    from agents.agent1_cv_matcher import run as run1
                    run1()
                    refresh_logs()
                except Exception as e:
                    set_agent(1, "CV Matcher", "failed", str(e))
                    refresh_logs()

                # Check if CV matched any JD
                with get_connection() as conn:
                    matched_count = conn.execute(
                        "SELECT COUNT(*) FROM matches WHERE match_score >= 70"
                    ).fetchone()[0]

                if matched_count == 0:
                    set_agent(1, "CV Matcher", "skipped", "No match found (score < 70) — pipeline stopped")
                    set_agent(2, "Extractor", "skipped", "Skipped — CV did not match any Job Description")
                    set_agent(3, "WhatsApp",  "skipped", "Skipped — CV did not match any Job Description")
                    set_agent(4, "AI Caller", "skipped", "Skipped — CV did not match any Job Description")
                    root_logger.removeHandler(handler)
                    st.markdown("""
                    <div style="
                        background: linear-gradient(135deg, #fff1f2 0%, #fce7f3 100%);
                        border: 2px solid #fda4af;
                        border-radius: 16px;
                        padding: 36px 28px;
                        text-align: center;
                        margin-top: 24px;
                    ">
                        <div style="font-size: 4rem; margin-bottom: 12px;">😔</div>
                        <div style="font-size: 1.4rem; font-weight: 700; color: #9f1239; margin-bottom: 8px;">
                            Not a Match
                        </div>
                        <div style="font-size: 1rem; color: #be123c; margin-bottom: 16px;">
                            This CV scored below 70 on all Job Descriptions.<br>
                            No action has been taken for this candidate.
                        </div>
                        <div style="
                            display: inline-block;
                            background: #fda4af;
                            color: #7f1d1d;
                            font-size: 0.82rem;
                            font-weight: 600;
                            padding: 6px 18px;
                            border-radius: 20px;
                        ">Match score &lt; 70 · Pipeline stopped</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    set_agent(1, "CV Matcher", "done", f"Matched {matched_count} JD(s)")

                    # ── Agent 2: Extractor ────────────────────────────────────
                    set_agent(2, "Extractor", "running", "Extracting contact info...")
                    try:
                        from agents.agent2_extractor import run as run2
                        run2()
                        set_agent(2, "Extractor", "done", "Contact info extracted")
                        refresh_logs()
                    except Exception as e:
                        set_agent(2, "Extractor", "failed", str(e))
                        refresh_logs()

                    # ── Agent 3: WhatsApp (disabled) ──────────────────────────
                    # Auto-mark whatsapp_sent=1 so Agent 4 can proceed
                    with get_connection() as conn:
                        conn.execute(
                            "UPDATE communications SET whatsapp_sent=1, whatsapp_sent_at=CURRENT_TIMESTAMP WHERE whatsapp_sent=0"
                        )
                    set_agent(3, "WhatsApp", "skipped", "Disabled — candidates auto-marked for calling")

                    # ── Agent 4: AI Caller ────────────────────────────────────
                    set_agent(4, "AI Caller", "running", "Initiating Bolna call...")
                    try:
                        from agents.agent4_caller import run as run4
                        run4()
                        set_agent(4, "AI Caller", "done", "Call queued · Invite will be sent after candidate confirms slot")
                        refresh_logs()
                    except Exception as e:
                        set_agent(4, "AI Caller", "failed", str(e))
                        refresh_logs()

                    root_logger.removeHandler(handler)
                    st.balloons()
                    st.success("🎉 Pipeline complete! Switch to **Candidates** to see results.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Overview
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📊 Overview":
    st.title("📊 Pipeline Overview")
    st.caption(f"Last refreshed: {datetime.now().strftime('%d %b %Y, %I:%M %p')}")

    m = get_metrics()
    col1, col2, col3 = st.columns(3)

    def metric_card(col, icon, label, value, color="#1e40af"):
        col.markdown(f"""
        <div class="metric-card">
            <div style="font-size:2rem">{icon}</div>
            <div class="metric-value" style="color:{color}">{value}</div>
            <div class="metric-label">{label}</div>
        </div>""", unsafe_allow_html=True)

    metric_card(col1, "📄", "CVs Processed",    m["cvs"])
    metric_card(col2, "💼", "Job Descriptions",  m["jds"])
    metric_card(col3, "✅", "Candidates Matched", m["matched"], "#059669")

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
    col4, col5, col6 = st.columns(3)
    metric_card(col4, "💬", "WhatsApp Sent",      m["wa"],      "#d97706")
    metric_card(col5, "📞", "Calls Initiated",    m["calls"],   "#7c3aed")
    metric_card(col6, "📅", "Invites Sent",       m["invites"], "#db2777")

    st.divider()
    st.subheader("Pipeline Funnel")
    st.bar_chart(pd.DataFrame({
        "Stage": ["CVs Processed", "Matched (≥70)", "WhatsApp Sent", "Calls Made", "Invites Sent"],
        "Count": [m["cvs"], m["matched"], m["wa"], m["calls"], m["invites"]],
    }).set_index("Stage"))

    candidates = get_candidates()
    if candidates:
        st.subheader("Interview Status")
        statuses = {}
        for c in candidates:
            s = c["interview_status"] or "Pending"
            statuses[s] = statuses.get(s, 0) + 1
        st.bar_chart(pd.DataFrame(list(statuses.items()), columns=["Status", "Count"]).set_index("Status"))


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Job Descriptions
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💼 Job Descriptions":
    st.title("💼 Job Descriptions")
    st.caption("All JDs loaded from the job_descriptions folder.")

    jds = get_job_descriptions()
    if not jds:
        st.info("No job descriptions found. Add PDF or TXT files to `data/job_descriptions/` and run the pipeline.")
    else:
        st.caption(f"{len(jds)} job description{'s' if len(jds) != 1 else ''} loaded")
        for jd in jds:
            matched   = jd["matched"] or 0
            total     = jd["total_applicants"] or 0
            match_pct = f"{matched}/{total} matched" if total else "No CVs screened yet"
            badge_color = "#059669" if matched > 0 else "#94a3b8"

            with st.expander(f"**{jd['title']}**  —  {match_pct}", expanded=False):
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Applicants", total)
                col2.metric("Matched (≥70)", matched)
                col3.metric("Match Rate", f"{int(matched/total*100)}%" if total else "—")
                st.divider()
                st.text_area(
                    "Job Description Content",
                    value=jd["content"],
                    height=300,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"jd_content_{jd['jd_id']}",
                )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Candidates
# ══════════════════════════════════════════════════════════════════════════════
elif page == "👥 Candidates":
    st.title("👥 Candidates")

    STATUS_COLORS = {
        "Pending":   "#94a3b8", "Scheduled": "#3b82f6",
        "Completed": "#10b981", "Selected":  "#059669",
        "Rejected":  "#ef4444", "On Hold":   "#f59e0b",
    }

    candidates = get_candidates()
    if not candidates:
        st.info("No matched candidates yet. Upload a CV to get started.")
    else:
        for c in candidates:
            score        = c["top_score"]
            score_color  = "#10b981" if score >= 80 else "#f59e0b" if score >= 70 else "#94a3b8"
            status       = c["interview_status"] or "Pending"
            status_color = STATUS_COLORS.get(status, "#94a3b8")

            st.markdown("<div style='border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin-bottom:12px'>", unsafe_allow_html=True)
            with st.container():
                col1, col2, col3 = st.columns([3, 2, 2])
                with col1:
                    st.markdown(f"### {c['name'] or '—'}")
                    st.caption(f"📱 {c['phone'] or '—'}   |   📧 {c['email'] or '—'}")
                    if c["matched_jds"]:
                        st.caption(f"💼 {c['matched_jds']}")
                with col2:
                    st.markdown("**Match Score**")
                    st.markdown(f"<span style='font-size:1.8rem;font-weight:700;color:{score_color}'>{score}</span>/100", unsafe_allow_html=True)
                    comms = []
                    if c["whatsapp_sent"]: comms.append("💬 WhatsApp")
                    if c["call_made"]:     comms.append("📞 Called")
                    if c["invite_sent"]:   comms.append("📅 Invite")
                    st.caption("  ".join(comms) if comms else "No contact yet")
                with col3:
                    st.markdown("**Interview Status**")
                    st.markdown(f"<span class='status-pill' style='background:{status_color}22;color:{status_color}'>{status}</span>", unsafe_allow_html=True)
                    if c["rating"]:
                        st.markdown("⭐" * c["rating"] + "☆" * (5 - c["rating"]))
                    if c["interview_date"]:
                        st.caption(f"📆 {c['interview_date']}")
            st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Interview Feedback
# ══════════════════════════════════════════════════════════════════════════════
elif page == "✍️ Interview Feedback":
    st.title("✍️ Interview Feedback")
    st.caption("Update candidate status and add post-interview notes.")

    col_poll, _ = st.columns([1, 3])
    with col_poll:
        if st.button("🔄 Check Call Results", help="Poll Bolna for completed calls and save chosen interview slots"):
            from agents.agent4_caller import poll_call_results
            with st.spinner("Polling Bolna..."):
                poll_call_results()
            st.success("Done — interview slots updated.")
            st.experimental_rerun()

    candidates = [c for c in get_candidates() if c["name"]]
    if not candidates:
        st.info("No matched candidates yet.")
    else:
        names = [f"{c['name']} (Score: {c['top_score']})" for c in candidates]
        selected_idx = st.selectbox("Select Candidate", range(len(names)), format_func=lambda i: names[i])
        c = candidates[selected_idx]

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Name:** {c['name']}")
            st.markdown(f"**Phone:** {c['phone'] or '—'}")
            st.markdown(f"**Matched JDs:** {c['matched_jds'] or '—'}")
        with col2:
            st.markdown(f"**Match Score:** {c['top_score']}/100")
            st.markdown(
                f"**WhatsApp:** {'✅' if c['whatsapp_sent'] else '❌'}  "
                f"**Call:** {'✅' if c['call_made'] else '❌'}  "
                f"**Invite:** {'✅' if c['invite_sent'] else '❌'}"
            )

        st.divider()
        st.subheader("Update Interview Details")
        STATUS_OPTIONS = ["Pending", "Scheduled", "Completed", "Selected", "Rejected", "On Hold"]

        with st.form(f"feedback_{c['candidate_id']}"):
            status = st.selectbox("Interview Status", STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(c["interview_status"] or "Pending"))
            interview_date = st.text_input("Interview Date",
                value=c["interview_date"] or "", placeholder="e.g. 25 Mar 2026, 10:00 AM")
            rating = st.slider("Rating", 0, 5, c["rating"] or 0)
            feedback = st.text_area("Feedback / Notes", value=c["interview_feedback"] or "",
                height=150, placeholder="e.g. Strong technical skills, recommended for next round.")

            if st.form_submit_button("💾 Save Feedback", type="primary", use_container_width=True):
                update_feedback(c["candidate_id"], status, feedback, interview_date, rating)
                st.success(f"✅ Feedback saved for {c['name']}")
                st.experimental_rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Match Scores
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📈 Match Scores":
    st.title("📈 Match Scores")

    scores = get_all_scores()
    if not scores:
        st.info("No scores yet. Upload a CV to get started.")
    else:
        df = pd.DataFrame(scores).rename(columns={
            "name": "Candidate",
            "title": "Job Description",
            "match_score": "Score",
        })
        df = df.sort_values("Score", ascending=False).reset_index(drop=True)

        # Score cards
        for _, row in df.iterrows():
            score = row["Score"]
            if score >= 80:
                color, bg, badge, label = "#065f46", "#d1fae5", "🟢", "Strong Match"
            elif score >= 70:
                color, bg, badge, label = "#92400e", "#fef3c7", "🟡", "Match"
            else:
                color, bg, badge, label = "#991b1b", "#fee2e2", "🔴", "No Match"

            st.markdown(f"""
            <div style="background:{bg};border-radius:10px;padding:14px 18px;
                        margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;">
                <div>
                    <div style="font-weight:700;font-size:1rem;color:#0f172a">{row['Candidate']}</div>
                    <div style="font-size:0.85rem;color:#475569;margin-top:2px">{row['Job Description']}</div>
                </div>
                <div style="text-align:right">
                    <div style="font-size:1.6rem;font-weight:800;color:{color}">{score}</div>
                    <div style="font-size:0.75rem;color:{color};font-weight:600">{badge} {label}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.divider()
        st.caption(f"Threshold: ≥70 to match · {len(df[df['Score'] >= 70])} of {len(df)} passed")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Architecture
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🏗 Architecture":
    st.title("🏗 System Architecture")
    st.caption("End-to-end flow of the Recruitment AI pipeline.")
    arch_path = BASE_DIR / "assets" / "architecture.png"
    if arch_path.exists():
        st.image(str(arch_path), use_column_width=True)
    else:
        st.error("Architecture diagram not found at assets/architecture.png")
