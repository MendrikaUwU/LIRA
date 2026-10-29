# LIRA — Learning Intrusion Reasoning Agent

**ML detects. LLM investigates, explains and guides.**

LIRA is a prototype for investigating a selected network-flow record from a CSV. A Random Forest provides the initial class prediction; Muse Spark Open (through Baseten) selects among bounded, Python-validated analysis tools and helps produce a Markdown report.

> This is a research/demo tool, not a real-time monitor or automatic blocking system. A model prediction is not proof of a real-world attack.

## Project files

- `app.py` — Streamlit interface for CSV upload, row selection, detection, investigation and report download.
- `lira_engine.py` — detection, investigation state, authorized tools, Muse Spark call and Markdown report.
- `requirements.txt` — Python dependencies.
- `.env.example` — names of configuration variables only; no real credentials.

## Required runtime configuration

The trained model file is intentionally **not included** in this repository. Place `lira_rf_baseline.joblib` in a local `models/` directory or set `LIRA_MODEL_PATH` to its actual location. The artifact must contain `model` and `features` keys, as in the existing Colab notebook.

Set `BASETEN_API_KEY` as an environment variable or deployment secret. Never put the real key in source code, README, notebook outputs, screenshots, or GitHub commits.

Optional: set `LIRA_REFERENCE_CSV` to a compatible CSV containing all model features and a `Label` (or `label`/`class`) column. This enables `compare_similar_flows`; without it, that tool is not offered to Muse Spark.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
# Set BASETEN_API_KEY and LIRA_MODEL_PATH in your environment.
streamlit run app.py
```

## Deployment note

GitHub stores the source; it does not run the app by itself. A Streamlit-compatible host or another Python hosting service is needed to run `app.py`. Configure `BASETEN_API_KEY` and the model artifact securely in the hosting environment. Do not commit the complete CIC-IDS2017 dataset or the trained model to the source repository.

## Current scope and limitations

- CSV upload and one-row-at-a-time analysis.
- Maximum of three additional analysis actions per investigation.
- Python validates the LLM's decision and executes only registered tools.
- Similar-flow comparison requires a separately configured reference CSV.
- Results are dataset-based and require human review; model probabilities may not be calibrated.
