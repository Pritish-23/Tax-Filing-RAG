import streamlit as st
import requests
import time
from datetime import datetime
import os

# ── config ────────────────────────────────────────────────────────────────────

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api")
SESSION_TTL     = 30 * 60  # 30 minutes in seconds

# ── page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Tax Filing Assistant",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── helpers ───────────────────────────────────────────────────────────────────

def format_inr(amount: int) -> str:
    if amount >= 100000:
        return f"₹{amount/100000:.2f}L"
    return f"₹{amount:,}"

def time_remaining(created_at: float) -> str:
    elapsed  = time.time() - created_at
    remaining = max(0, SESSION_TTL - elapsed)
    mins = int(remaining // 60)
    secs = int(remaining % 60)
    return f"{mins:02d}:{secs:02d}"

def delete_session():
    if st.session_state.get("session_id"):
        try:
            requests.delete(f"{API_BASE}/session/{st.session_state.session_id}")
        except Exception:
            pass
    for key in ["session_id", "employee_name", "assessment_year",
                "gross_salary", "analysis", "chat_history", "session_created_at"]:
        st.session_state.pop(key, None)
    st.rerun()

def check_session_alive() -> bool:
    sid = st.session_state.get("session_id")
    if not sid:
        return False
    try:
        r = requests.get(f"{API_BASE}/session/{sid}/status", timeout=3)
        return r.json().get("exists", False)
    except Exception:
        return False

# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🧾 Tax Assistant")
    st.caption("Privacy-first tax filing for salaried individuals")
    st.divider()

    if st.session_state.get("session_id"):
        st.success(f"Session active")
        st.caption(f"👤 {st.session_state.get('employee_name', '')}")
        st.caption(f"📅 AY {st.session_state.get('assessment_year', '')}")
        st.caption(f"💼 Gross: {format_inr(st.session_state.get('gross_salary', 0))}")

        st.divider()

        ## Live timer using JavaScript — runs in browser, no page flicker
        created_at = st.session_state.get("session_created_at", time.time())
        elapsed    = int(time.time() - created_at)
        remaining  = max(0, SESSION_TTL - elapsed)

        # Show expiry time instead of countdown — simpler and cleaner
        created_at  = st.session_state.get("session_created_at", time.time())
        expires_at  = created_at + SESSION_TTL
        expire_time = datetime.fromtimestamp(expires_at).strftime("%I:%M %p")
        st.caption(f"⏱ Data auto-clears at **{expire_time}**")
        st.caption("Your data is stored in memory only and never saved to disk.")

        st.divider()

        # Delete button — front and center
        if st.button("🗑 Delete My Data Now", type="primary", use_container_width=True):
            delete_session()
            st.success("All your data has been deleted.")

    else:
        st.info("Upload your documents to get started.")
        st.divider()
        st.caption("**Privacy commitment:**")
        st.caption("• Documents processed in memory only")
        st.caption("• Data auto-cleared after 30 min inactivity")
        st.caption("• No data written to disk or logs")
        st.caption("• Delete anytime with one click")

# ── main area ─────────────────────────────────────────────────────────────────

if not st.session_state.get("session_id"):

    # ── upload page ───────────────────────────────────────────────────────────
    st.title("🧾 Indian Income Tax Filing Assistant")
    st.subheader("For salaried individuals — AY 2025-26 and AY 2026-27")
    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📄 Upload Documents")
        form16        = st.file_uploader("Form 16 (PDF)", type=["pdf"])
        bank_statement = st.file_uploader("Bank Statement (CSV)", type=["csv"])

    with col2:
        st.markdown("### ⚙️ Your Details")
        is_metro = st.selectbox(
            "City type (affects HRA exemption)",
            options=[False, True],
            format_func=lambda x: "Metro (Mumbai/Delhi/Kolkata/Chennai)" if x else "Non-metro",
        )
        parents_senior_citizen = st.selectbox(
            "Are your parents senior citizens? (affects 80D limit)",
            options=[False, True],
            format_func=lambda x: "Yes (80D limit: ₹50,000)" if x else "No (80D limit: ₹25,000)",
        )

    st.divider()

    if form16 and bank_statement:
        if st.button("🚀 Analyse My Tax", type="primary", use_container_width=True):
            with st.spinner("Extracting your documents and computing tax analysis..."):
                try:
                    response = requests.post(
                        f"{API_BASE}/upload",
                        files={
                            "form16":         (form16.name, form16.getvalue(), "application/pdf"),
                            "bank_statement":  (bank_statement.name, bank_statement.getvalue(), "text/csv"),
                        },
                        data={
                            "is_metro":               str(is_metro).lower(),
                            "parents_senior_citizen": str(parents_senior_citizen).lower(),
                        },
                        timeout=60,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        st.session_state.session_id        = data["session_id"]
                        st.session_state.employee_name     = data["employee_name"]
                        st.session_state.assessment_year   = data["assessment_year"]
                        st.session_state.gross_salary      = data["gross_salary"]
                        st.session_state.session_created_at = time.time()
                        st.session_state.chat_history      = []
                        st.rerun()
                    else:
                        st.error(f"Upload failed: {response.json().get('detail', 'Unknown error')}")

                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to the API. Make sure FastAPI is running on port 8000.")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
    else:
        st.info("Please upload both your Form 16 PDF and bank statement CSV to proceed.")

else:

    # ── analysis + chat page ──────────────────────────────────────────────────

    # Check session is still alive
    if not check_session_alive():
        st.warning("Your session has expired. Please re-upload your documents.")
        for key in ["session_id", "employee_name", "assessment_year",
                    "gross_salary", "analysis", "chat_history", "session_created_at"]:
            st.session_state.pop(key, None)
        st.rerun()

    sid = st.session_state.session_id

    # Load analysis if not already cached
    if "analysis" not in st.session_state:
        with st.spinner("Generating tax analysis..."):
            try:
                r = requests.get(f"{API_BASE}/analysis/{sid}", timeout=60)
                if r.status_code == 200:
                    st.session_state.analysis = r.json()
                else:
                    st.error(f"Failed to load analysis: {r.json().get('detail')}")
                    st.stop()
            except Exception as e:
                st.error(f"Error loading analysis: {str(e)}")
                st.stop()

    analysis = st.session_state.analysis

    # ── tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2 = st.tabs(["📊 Tax Analysis", "💬 Ask Questions"])

    # ── tab 1: regime comparison ──────────────────────────────────────────────
    with tab1:
        st.title(f"Tax Analysis — AY {analysis['assessment_year']}")

        # Recommendation banner
        rec = analysis["recommended_regime"].upper()
        savings = analysis["savings"]
        if rec == "NEW":
            st.success(f"✅ **New Regime recommended** — saves you {format_inr(savings)}")
        elif rec == "OLD":
            st.success(f"✅ **Old Regime recommended** — saves you {format_inr(savings)}")
        else:
            st.info("⚖️ **Borderline** — both regimes result in similar tax liability")

        st.divider()

        # Side by side regime comparison
        col1, col2 = st.columns(2)

        with col1:
            o = analysis["old_regime"]
            st.markdown("### 🏛 Old Regime")
            st.metric("Taxable Income",  format_inr(o["taxable_income"]))
            st.metric("Total Tax",       format_inr(o["total_tax"]))
            st.metric("Effective Rate",  f"{o['effective_rate_pct']}%")
            if o["rebate_87A"] > 0:
                st.metric("Rebate 87A",  format_inr(o["rebate_87A"]))
            if o["surcharge"] > 0:
                st.metric("Surcharge",   format_inr(o["surcharge"]))

        with col2:
            n = analysis["new_regime"]
            st.markdown("### 🆕 New Regime")
            st.metric("Taxable Income",  format_inr(n["taxable_income"]))
            st.metric("Total Tax",       format_inr(n["total_tax"]))
            st.metric("Effective Rate",  f"{n['effective_rate_pct']}%")
            if n["rebate_87A"] > 0:
                st.metric("Rebate 87A",  format_inr(n["rebate_87A"]))
            if n["surcharge"] > 0:
                st.metric("Surcharge",   format_inr(n["surcharge"]))

        st.divider()

        # Deduction breakdown
        st.markdown("### 📋 Your Deductions (Old Regime)")
        d = analysis["deductions"]

        dcol1, dcol2, dcol3, dcol4 = st.columns(4)
        dcol1.metric("Standard Deduction", format_inr(d["standard_deduction"]))
        dcol2.metric("Section 80C",        format_inr(d["deduction_80C"]))
        dcol3.metric("Section 80D",        format_inr(d["deduction_80D"]))
        dcol4.metric("HRA Exemption",      format_inr(d["hra_exemption"]))

        st.metric("Total Deductions", format_inr(d["total"]))

        if d["unused_80C_capacity"] > 0:
            st.info(f"💡 You have {format_inr(d['unused_80C_capacity'])} of unused 80C capacity. "
                    f"Investing more in PPF, ELSS, or LIC could reduce your old regime tax further.")

        st.divider()

        # LLM explanation
        st.markdown("### 🤖 Detailed Explanation")
        st.markdown(analysis["explanation"])

    # ── tab 2: chat ───────────────────────────────────────────────────────────
    with tab2:
        st.title("💬 Ask Tax Questions")
        st.caption("Ask anything about your deductions, HRA, regime choice, or filing requirements.")

        # Chat history
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input
        if prompt := st.chat_input("Ask a tax question..."):
            # Show user message
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # Get answer
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    try:
                        r = requests.post(
                            f"{API_BASE}/chat/{sid}",
                            json={"message": prompt},
                            timeout=60,
                        )
                        if r.status_code == 200:
                            answer = r.json()["answer"]
                        else:
                            answer = f"Error: {r.json().get('detail', 'Unknown error')}"
                    except Exception as e:
                        answer = f"Error connecting to API: {str(e)}"

                st.markdown(answer)
                st.session_state.chat_history.append({"role": "assistant", "content": answer})