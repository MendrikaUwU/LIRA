# LIRA — Learning Intrusion Reasoning Agent

**ML detects. LLM investigates, explains and guides.**

LIRA is a prototype for investigating selected network-flow records from a CSV file. A Random Forest model provides the initial class prediction, while Muse Spark Open, accessed through Baseten, guides a bounded investigation by selecting among Python-validated analysis tools. LIRA then produces an accessible Markdown report with findings, uncertainties and defensive recommendations.

> LIRA is a research and demonstration tool. It is not a real-time network monitoring or automatic traffic-blocking system. A model prediction is not proof of a real-world attack.

## Project structure

- `api.py` — FastAPI backend, API endpoints, investigation handling and PDF report generation.
- `lira_engine.py` — Random Forest detection, investigation state, authorized analysis tools, Muse Spark integration and Markdown report generation.
- `frontend/` — HTML, CSS and JavaScript interface.
- `requirements.txt` — Python dependencies.
- `.env.example` — example configuration variable names; contains no real credentials.

## Runtime configuration

The trained model is intentionally not included in this repository.

Place `lira_rf_baseline.joblib` in the local `models/` directory, or set `LIRA_MODEL_PATH` to the actual model file location. The artifact must contain the `model` and `features` keys used by the project.

Set `BASETEN_API_KEY` as an environment variable or deployment secret. Never include the real API key in source code, notebooks, screenshots, README files or GitHub commits.

Optional: set `LIRA_REFERENCE_CSV` to a compatible reference dataset containing the required model features and a `Label` (or `label`/`class`) column. This enables the `compare_similar_flows` analysis tool. Without a compatible reference dataset, that analysis is unavailable.

## Run locally

Create and activate a virtual environment:

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Configure the required environment variables:

```bash
# Linux/macOS
export BASETEN_API_KEY="your_api_key"
export LIRA_MODEL_PATH="models/lira_rf_baseline.joblib"

# Windows PowerShell
$env:BASETEN_API_KEY="your_api_key"
$env:LIRA_MODEL_PATH="models/lira_rf_baseline.joblib"
```

Start the FastAPI server from the project root:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

The API documentation is available at:

```text
http://127.0.0.1:8000/docs
```

The frontend is served by the application when configured through the backend.

## Deployment

GitHub stores the project source code but does not run the application by itself. Deployment requires a Python hosting service that supports FastAPI and an ASGI server such as Uvicorn.

The deployment environment must provide:

- The project source code.
- The trained model artifact, stored separately from the source repository.
- The `BASETEN_API_KEY` secret.
- Any optional reference dataset required for similar-flow analysis.

The application must be configured to use the correct model path and hosting port. Never commit the complete CIC-IDS2017 dataset, trained model artifacts or API credentials to the source repository.

## Current scope and limitations

- CSV-based analysis of a selected network-flow record.
- Random Forest initial classification using 78 numerical features.
- LLM-guided investigation using registered Python analysis tools.
- Maximum of three additional analysis actions per investigation.
- Python-side validation of proposed LLM decisions and authorized tool execution.
- Markdown investigation report and PDF export.
- Similar-flow comparison requires a separately configured reference dataset.
- Model probabilities may not be calibrated and should not be interpreted as absolute certainty.
- Findings are based on the supplied dataset and require human review.

## Try LIRA

**Live Demo:** [Launch LIRA](https://lira-gre5.onrender.com/)

**Sample Dataset:** [Download lira_test(1).csv](./lira_test (1).csv)

### How to use

1. Download the sample CSV file.
2. Open the LIRA live demo.
3. Upload `lira_test (1).csv`.
4. Start the investigation.
5. Review the detection results and investigation evidence.
6. Download the generated PDF report.

### Important Note

LIRA is a prototype designed for network traffic analysis and investigation assistance. Its predictions are not definitive proof of malicious activity. The generated recommendations should be reviewed by a human operator.

## Project status

LIRA is an evolving prototype. Its detection, investigation workflow, API and report-generation components have been developed and tested. Further evaluation is needed to assess its behavior on additional data and its usefulness in practical cybersecurity investigations.
