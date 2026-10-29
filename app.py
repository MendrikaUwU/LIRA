import os
import uuid
import pandas as pd
import streamlit as st

from lira_engine import (
    LIRAInvestigation, initialize_reference_data, lira_detect,
    lira_render_markdown_report, lira_run_llm_investigation, load_model,
)

st.set_page_config(page_title="LIRA | Network Security Investigation", page_icon="🛡️", layout="wide")
st.title("🛡️ LIRA")
st.caption("Learning Intrusion Reasoning Agent · ML detects. LLM investigates, explains and guides.")
st.info("LIRA provides decision support from dataset records. A model prediction is not proof of a real-world attack; verify findings with an operator.")

@st.cache_resource(show_spinner=False)
def prepare_engine():
    load_model()
    initialize_reference_data()
    return True

try:
    prepare_engine()
    engine_ready = True
except Exception as exc:
    engine_ready = False
    st.error("The detection model is not configured yet.")
    st.code(str(exc))
    st.markdown("Set `LIRA_MODEL_PATH` to the location of `lira_rf_baseline.joblib`. Keep the model file and API key outside the GitHub repository.")

uploaded = st.file_uploader("Upload a network-flow CSV", type=["csv"], disabled=not engine_ready)
if uploaded is not None and engine_ready:
    try:
        df = pd.read_csv(uploaded, low_memory=False)
    except Exception as exc:
        st.error(f"Could not read CSV: {exc}")
        st.stop()
    if df.empty:
        st.warning("The uploaded CSV contains no rows.")
        st.stop()
    st.write(f"Loaded **{len(df):,} rows** and **{len(df.columns):,} columns**.")
    excluded = {"Label", "label", "class", "source_file", "Flow ID", "Timestamp"}
    selectable = [i for i in range(len(df))]
    selected = st.selectbox("Choose the row to investigate", selectable, format_func=lambda i: f"Row {i + 1}")
    with st.expander("Preview selected row"):
        st.dataframe(df.iloc[[selected]].head(1), use_container_width=True)
    if st.button("Run LIRA investigation", type="primary"):
        row = df.iloc[selected].drop(labels=[c for c in excluded if c in df.columns], errors="ignore")
        try:
            with st.spinner("Running Random Forest detection…"):
                detection = lira_detect(row)
            st.session_state["lira_detection"] = detection
            st.session_state["lira_row"] = row
            st.session_state["lira_result"] = None
            st.session_state["lira_report"] = None
        except Exception as exc:
            st.error(f"Detection could not run: {exc}")

if engine_ready and st.session_state.get("lira_detection"):
    detection = st.session_state["lira_detection"]
    st.subheader("Initial detection")
    c1, c2, c3 = st.columns(3)
    c1.metric("Predicted class", detection["prediction"])
    c2.metric("Status", detection["status"])
    c3.metric("Model confidence", f"{detection['confidence']:.1%}")
    with st.expander("Class probabilities"):
        st.dataframe(pd.DataFrame([{"Class": k, "Probability": v} for k, v in detection["probabilities"].items()]).sort_values("Probability", ascending=False), use_container_width=True, hide_index=True)
    if st.button("Ask Muse Spark to investigate", type="primary"):
        investigation = LIRAInvestigation(investigation_id=uuid.uuid4().hex[:10], initial_detection=detection)
        investigation.flow_features = st.session_state["lira_row"]
        with st.spinner("Muse Spark is investigating (up to 3 additional analyses)…"):
            result = lira_run_llm_investigation(investigation, verbose=False)
        report = lira_render_markdown_report(investigation, result, detection)
        st.session_state["lira_result"] = result
        st.session_state["lira_report"] = report
        st.session_state["lira_investigation"] = investigation

if st.session_state.get("lira_result"):
    result = st.session_state["lira_result"]
    st.subheader("Investigation result")
    st.write(f"**Status:** {result.get('status', 'UNKNOWN')} · **Analyses used:** {result.get('analyses_used', 0)} · **Remaining:** {result.get('analyses_remaining', 0)}")
    if result.get("error"):
        st.warning(f"The investigation did not complete normally: {result['error']}")
    with st.expander("Investigation history and evidence"):
        st.json(result.get("investigation", {}))
    report = st.session_state["lira_report"]
    st.markdown(report)
    st.download_button("Download Markdown report", data=report, file_name="LIRA_investigation_report.md", mime="text/markdown")

with st.sidebar:
    st.header("Configuration")
    st.write("**LLM provider:** Muse Spark Open via Baseten")
    st.write("**Analysis budget:** Up to 3 additional tools")
    st.write("**API key:** `BASETEN_API_KEY` environment variable / deployment secret")
    st.caption("The optional similar-flow analysis is enabled only when LIRA_REFERENCE_CSV points to a compatible reference CSV.")
