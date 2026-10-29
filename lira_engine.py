"""LIRA engine: supervised detection + bounded, tool-controlled LLM investigation.

Required runtime artifacts are deliberately kept outside Git: set LIRA_MODEL_PATH
and optionally LIRA_REFERENCE_CSV. Never commit API keys, models, or datasets.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

MODEL_PATH = os.environ.get("LIRA_MODEL_PATH", "models/lira_rf_baseline.joblib")
model = None
feature_cols: list[str] = []
_reference_X = None
_reference_y = None
_reference_scaler = None
_neighbors = None


def load_model(path: str | None = None):
    """Load the saved dictionary containing `model` and `features`."""
    global model, feature_cols
    chosen = Path(path or MODEL_PATH).expanduser()
    if not chosen.is_file():
        raise FileNotFoundError(
            f"LIRA model not found at '{chosen}'. Set LIRA_MODEL_PATH to the "
            "path of lira_rf_baseline.joblib; do not upload it to public GitHub."
        )
    saved = joblib.load(chosen)
    if not isinstance(saved, dict) or "model" not in saved or "features" not in saved:
        raise ValueError("Model artifact must contain 'model' and 'features'.")
    model = saved["model"]
    feature_cols = list(saved["features"])
    if not feature_cols or not hasattr(model, "predict") or not hasattr(model, "predict_proba"):
        raise ValueError("Model artifact is missing required model/features.")
    return model


def lira_detect(row):
    if model is None or not feature_cols:
        load_model()
    if isinstance(row, pd.DataFrame):
        X = row.copy()
    elif isinstance(row, pd.Series):
        X = row.to_frame().T
    else:
        raise TypeError("Input must be a pandas Series or DataFrame.")
    missing = [c for c in feature_cols if c not in X.columns]
    if missing:
        raise ValueError(f"Missing required features ({len(missing)}): {missing[:10]}")
    X = X[feature_cols].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if X.isna().any().any():
        raise ValueError("Input contains missing, non-numeric, or non-finite feature values.")
    predictions = model.predict(X)
    probabilities = model.predict_proba(X)
    results = []
    for label, probs in zip(predictions, probabilities):
        results.append({
            "prediction": str(label),
            "status": "NORMAL" if str(label) == "BENIGN" else "ATTACK",
            "confidence": round(float(np.max(probs)), 4),
            "probabilities": {str(cls): round(float(prob), 4) for cls, prob in zip(model.classes_, probs)},
        })
    return results[0] if len(results) == 1 else results


@dataclass
class LIRAInvestigation:
    investigation_id: str
    initial_detection: dict
    max_additional_analyses: int = 3
    evidence: list[dict[str, Any]] = field(default_factory=list)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    status: str = "IN_PROGRESS"
    final_conclusion: str | None = None

    @property
    def analyses_used(self) -> int:
        return len(self.action_history)

    @property
    def remaining_analyses(self) -> int:
        return max(0, self.max_additional_analyses - self.analyses_used)

    def add_evidence(self, tool_name: str, result: dict):
        self.evidence.append({"tool": tool_name, "result": result, "timestamp": datetime.now(timezone.utc).isoformat()})

    def record_action(self, tool_name: str, reason: str, outcome: str):
        self.action_history.append({"tool": tool_name, "reason": reason, "outcome": outcome})

    def stop(self, conclusion: str):
        self.status = "COMPLETED"
        self.final_conclusion = conclusion

    def to_dict(self) -> dict:
        return {
            "investigation_id": self.investigation_id, "initial_detection": self.initial_detection,
            "evidence": self.evidence, "action_history": self.action_history,
            "uncertainties": self.uncertainties, "analyses_used": self.analyses_used,
            "remaining_analyses": self.remaining_analyses, "status": self.status,
            "final_conclusion": self.final_conclusion,
        }


LIRA_TOOL_REGISTRY = {
    "analyze_prediction": {"description": "Examines predicted class, probabilities, and ambiguity.", "purpose": "Assess uncertainty in the initial detection.", "requires": ["initial_detection"]},
    "check_data_quality": {"description": "Checks required features and invalid values.", "purpose": "Determine whether input data is usable.", "requires": ["flow_features"]},
    "review_class_context": {"description": "Provides dataset-label context and cautions.", "purpose": "Clarify what can and cannot be concluded.", "requires": ["initial_detection", "dataset_context"]},
}


def initialize_reference_data(path: str | None = None, max_rows: int = 5000) -> bool:
    """Optionally enable similar-flow comparison from an external reference CSV."""
    global _reference_X, _reference_y, _reference_scaler, _neighbors
    path = path or os.environ.get("LIRA_REFERENCE_CSV")
    if not path or not Path(path).is_file() or model is None:
        return False
    df = pd.read_csv(path, low_memory=False)
    label_col = next((c for c in ("Label", "label", "class") if c in df.columns), None)
    if label_col is None:
        return False
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        return False
    X = df[feature_cols].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    valid = X.notna().all(axis=1)
    X, y = X.loc[valid], df.loc[valid, label_col].astype(str)
    if X.empty:
        return False
    if len(X) > max_rows:
        X = X.sample(n=max_rows, random_state=42)
        y = y.loc[X.index]
    _reference_X, _reference_y = X.reset_index(drop=True), y.reset_index(drop=True)
    _reference_scaler = StandardScaler()
    scaled = _reference_scaler.fit_transform(_reference_X)
    _neighbors = NearestNeighbors(n_neighbors=min(5, len(_reference_X)), metric="euclidean", n_jobs=-1).fit(scaled)
    LIRA_TOOL_REGISTRY["compare_similar_flows"] = {
        "description": "Compares a flow against available reference observations.",
        "purpose": "Provide context from nearby reference flows; not proof of an attack.",
        "requires": ["flow_features", "reference_data"],
    }
    return True


def lira_analyze_prediction(detection: dict) -> dict:
    required = {"prediction", "status", "confidence", "probabilities"}
    if not isinstance(detection, dict) or not required.issubset(detection):
        raise ValueError("Detection result is missing required fields.")
    probs = {str(k): float(v) for k, v in detection["probabilities"].items()}
    if not probs or any(not np.isfinite(v) or v < 0 or v > 1 for v in probs.values()):
        raise ValueError("Class probabilities must be finite values between 0 and 1.")
    ranked = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    if not np.isclose(sum(probs.values()), 1.0, atol=1e-3):
        raise ValueError("Class probabilities do not sum to approximately 1.")
    gap = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0.0)
    uncertainty = "HIGH" if gap < 0.10 else "MODERATE" if gap < 0.30 else "LOW"
    return {
        "predicted_class": str(detection["prediction"]), "status": str(detection["status"]),
        "model_confidence": round(float(detection["confidence"]), 4),
        "top_probability": round(ranked[0][1], 4), "second_best_class": ranked[1][0] if len(ranked) > 1 else None,
        "probability_gap": round(gap, 4), "prediction_uncertainty": uncertainty,
        "requires_further_investigation": uncertainty != "LOW",
        "interpretation": "The leading class has a narrow probability margin." if uncertainty == "HIGH" else "The prediction has some ambiguity." if uncertainty == "MODERATE" else "The leading class is clearly ahead of alternatives.",
        "limitations": ["Random Forest probabilities may not be calibrated.", "A high probability does not prove an attack occurred."],
    }


def lira_check_data_quality(row) -> dict:
    X = row.to_frame().T if isinstance(row, pd.Series) else row.copy() if isinstance(row, pd.DataFrame) else None
    if X is None:
        raise TypeError("Input must be a pandas Series or DataFrame.")
    missing = [c for c in feature_cols if c not in X.columns]
    if missing:
        return {"tool": "check_data_quality", "valid": False, "status": "MISSING_FEATURES", "missing_features": missing, "missing_count": len(missing)}
    X = X[feature_cols].apply(pd.to_numeric, errors="coerce")
    missing_count = int(X.isna().sum().sum())
    infinite_count = int(np.isinf(X.to_numpy(dtype=float)).sum())
    return {"tool": "check_data_quality", "valid": missing_count == 0 and infinite_count == 0, "status": "VALID" if missing_count == 0 and infinite_count == 0 else "INVALID_VALUES", "rows_checked": len(X), "features_checked": len(feature_cols), "missing_or_non_numeric_values": missing_count, "infinite_values": infinite_count}


def lira_compare_similar_flows(row, k: int = 5) -> dict:
    if _neighbors is None or _reference_X is None:
        return {"tool": "compare_similar_flows", "status": "REFERENCE_DATA_UNAVAILABLE", "message": "Reference data has not been configured."}
    X = row.to_frame().T if isinstance(row, pd.Series) else row.copy() if isinstance(row, pd.DataFrame) else None
    if X is None:
        raise TypeError("Input must be a pandas Series or DataFrame.")
    missing = [c for c in feature_cols if c not in X.columns]
    if missing:
        return {"tool": "compare_similar_flows", "status": "MISSING_FEATURES", "missing_features": missing}
    X = X[feature_cols].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if X.isna().any().any():
        return {"tool": "compare_similar_flows", "status": "INVALID_INPUT", "message": "Query contains missing or non-finite values."}
    if not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer.")
    k_used = min(k, len(_reference_X))
    distances, indices = _neighbors.kneighbors(_reference_scaler.transform(X), n_neighbors=k_used)
    neighbors = [{"reference_label": str(_reference_y.iloc[idx]), "distance": round(float(distance), 4)} for distance, idx in zip(distances[0], indices[0])]
    counts = {}
    for item in neighbors:
        counts[item["reference_label"]] = counts.get(item["reference_label"], 0) + 1
    return {"tool": "compare_similar_flows", "status": "COMPLETED", "neighbors_requested": k, "neighbors_found": len(neighbors), "nearest_reference_distance": round(float(distances[0][0]), 4), "neighbor_labels": counts, "neighbors": neighbors, "limitations": ["Euclidean distance depends on feature representation.", "Nearest neighbors are not independent proof of an attack.", "Reference data may contain resampled observations."]}


LIRA_CLASS_CONTEXT = {
    "BENIGN": ("Traffic labeled as normal in the reference dataset.", "A BENIGN prediction does not guarantee traffic is safe."),
    "DDoS": ("Distributed denial-of-service traffic.", "The prediction alone does not establish real-world impact or source."),
    "DoS Hulk": ("A denial-of-service attack category in CIC-IDS2017.", "The prediction alone does not independently confirm an active attack."),
    "FTP-Patator": ("FTP password-guessing attack traffic in CIC-IDS2017.", "The prediction does not prove an account was compromised."),
    "PortScan": ("Traffic associated with port-scanning activity in CIC-IDS2017.", "Scanning can have legitimate uses; investigate surrounding context."),
    "SSH-Patator": ("SSH password-guessing attack traffic in CIC-IDS2017.", "The prediction does not prove successful authentication or compromise."),
}


def lira_review_class_context(detection: dict) -> dict:
    label = detection.get("prediction")
    if not isinstance(label, str):
        raise ValueError("Detection must contain a string prediction.")
    context = LIRA_CLASS_CONTEXT.get(label)
    if context is None:
        return {"tool": "review_class_context", "status": "UNKNOWN_CLASS", "predicted_class": label, "message": "No class-specific context is available."}
    return {"tool": "review_class_context", "status": "COMPLETED", "predicted_class": label, "dataset_description": context[0], "caution": context[1], "scope": "This describes dataset labels, not verified live incidents."}


def lira_validate_action(action: dict, investigation: LIRAInvestigation) -> dict:
    if not isinstance(action, dict): return {"valid": False, "reason": "Action must be a dictionary."}
    tool = action.get("tool")
    if not isinstance(tool, str) or tool not in LIRA_TOOL_REGISTRY: return {"valid": False, "reason": "Unknown or unauthorized tool."}
    if investigation.status != "IN_PROGRESS": return {"valid": False, "reason": "Investigation is not active."}
    if investigation.remaining_analyses <= 0: return {"valid": False, "reason": "Analysis limit reached."}
    if any(x["tool"] == tool for x in investigation.action_history): return {"valid": False, "reason": "Tool already used in this investigation."}
    reason = action.get("reason")
    if not isinstance(reason, str) or not reason.strip(): return {"valid": False, "reason": "A justification is required."}
    return {"valid": True, "tool": tool, "reason": reason.strip()}


def lira_execute_tool(tool_name: str, investigation: LIRAInvestigation) -> dict:
    if tool_name not in LIRA_TOOL_REGISTRY: raise ValueError(f"Unauthorized tool: {tool_name}")
    detection = investigation.initial_detection
    if tool_name == "analyze_prediction": result = lira_analyze_prediction(detection)
    elif tool_name == "check_data_quality":
        if not hasattr(investigation, "flow_features"): raise ValueError("Flow features are not attached to investigation.")
        result = lira_check_data_quality(investigation.flow_features)
    elif tool_name == "compare_similar_flows":
        if not hasattr(investigation, "flow_features"): raise ValueError("Flow features are not attached to investigation.")
        result = lira_compare_similar_flows(investigation.flow_features)
    elif tool_name == "review_class_context": result = lira_review_class_context(detection)
    else: raise ValueError(f"No executor available for {tool_name}")
    investigation.add_evidence(tool_name, result)
    return result


def lira_run_action(action: dict, investigation: LIRAInvestigation) -> dict:
    validation = lira_validate_action(action, investigation)
    if not validation["valid"]:
        return {"executed": False, "reason": validation["reason"], "remaining_analyses": investigation.remaining_analyses}
    tool, reason = validation["tool"], validation["reason"]
    try:
        result = lira_execute_tool(tool, investigation)
        investigation.record_action(tool, reason, "SUCCESS")
        return {"executed": True, "tool": tool, "reason": reason, "result": result, "remaining_analyses": investigation.remaining_analyses}
    except Exception as exc:
        investigation.record_action(tool, reason, f"ERROR: {type(exc).__name__}")
        return {"executed": False, "tool": tool, "reason": reason, "error": str(exc), "remaining_analyses": investigation.remaining_analyses}


LIRA_AGENT_SYSTEM_PROMPT = """You are LIRA, a defensive cybersecurity investigation agent for small businesses. Investigate a machine-learning network alert using only authorized tools and evidence. Never invent results or network events. A dataset prediction is not proof of a real-world attack. State uncertainty clearly and respect the remaining analysis budget. Return exactly one JSON object without Markdown fences, with keys decision, tool, reason, conclusion. decision is investigate or stop. For investigate, tool must be an available unused tool and conclusion must be null. For stop, tool must be null and conclusion must be a non-empty provisional conclusion."""
LIRA_DECISION_SCHEMA = {"type": "object", "properties": {"decision": {"type": "string", "enum": ["investigate", "stop"]}, "tool": {"type": ["string", "null"]}, "reason": {"type": "string"}, "conclusion": {"type": ["string", "null"]}}, "required": ["decision", "tool", "reason", "conclusion"], "additionalProperties": False}


def lira_build_agent_context(investigation: LIRAInvestigation) -> str:
    context = {"investigation_id": investigation.investigation_id, "initial_detection": investigation.initial_detection, "evidence_collected": investigation.evidence, "action_history": investigation.action_history, "uncertainties": investigation.uncertainties, "available_tools": {n: d for n, d in LIRA_TOOL_REGISTRY.items() if not any(a["tool"] == n for a in investigation.action_history)}, "analyses_remaining": investigation.remaining_analyses, "allowed_decisions": ["investigate", "stop"]}
    return json.dumps(context, indent=2, default=str)


def lira_parse_agent_decision(raw_response: str, investigation: LIRAInvestigation) -> dict:
    try: decision = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError): return {"valid": False, "reason": "The agent response is not valid JSON."}
    if not isinstance(decision, dict): return {"valid": False, "reason": "The agent response must be a JSON object."}
    required = {"decision", "tool", "reason", "conclusion"}
    if not required.issubset(decision): return {"valid": False, "reason": "The response is missing required fields."}
    if decision["decision"] not in {"investigate", "stop"}: return {"valid": False, "reason": "Decision must be investigate or stop."}
    if not isinstance(decision["reason"], str) or not decision["reason"].strip(): return {"valid": False, "reason": "A non-empty reason is required."}
    if decision["decision"] == "stop":
        if decision["tool"] is not None: return {"valid": False, "reason": "A stop decision must not specify a tool."}
        if not isinstance(decision["conclusion"], str) or not decision["conclusion"].strip(): return {"valid": False, "reason": "A stop decision requires a conclusion."}
        return {"valid": True, **decision}
    if investigation.remaining_analyses <= 0: return {"valid": False, "reason": "No additional analyses remain."}
    validation = lira_validate_action({"tool": decision["tool"], "reason": decision["reason"]}, investigation)
    if not validation["valid"]: return {"valid": False, "reason": validation["reason"]}
    if decision["conclusion"] is not None: return {"valid": False, "reason": "An investigation decision must use a null conclusion."}
    return {"valid": True, **decision}


def lira_prepare_llm_input(investigation: LIRAInvestigation) -> dict:
    return {"system_prompt": LIRA_AGENT_SYSTEM_PROMPT, "investigation_context": lira_build_agent_context(investigation), "decision_schema": LIRA_DECISION_SCHEMA, "available_tools": list(LIRA_TOOL_REGISTRY.keys()), "analyses_used": investigation.analyses_used, "remaining_analyses": investigation.remaining_analyses}


def lira_call_muse_spark(investigation: LIRAInvestigation) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The openai package is not installed. Run: pip install -r requirements.txt") from exc
    api_key = os.environ.get("BASETEN_API_KEY")
    if not api_key: raise RuntimeError("Missing BASETEN_API_KEY environment variable.")
    client = OpenAI(base_url="https://inference.baseten.co/v1", api_key=api_key, timeout=60.0, max_retries=2)
    inp = lira_prepare_llm_input(investigation)
    messages = [{"role": "system", "content": inp["system_prompt"]}, {"role": "user", "content": "Investigate the current network security alert. Use only available tools, respect the analysis budget, and return exactly one JSON decision matching the schema.\n\nInvestigation context:\n" + inp["investigation_context"] + "\n\nDecision schema:\n" + json.dumps(inp["decision_schema"], ensure_ascii=False) + "\n\nAvailable tools:\n" + json.dumps(inp["available_tools"], ensure_ascii=False)}]
    response = client.chat.completions.create(model="meta-models/muse-spark-open-1026", messages=messages, temperature=0, max_tokens=10000)
    content = response.choices[0].message.content
    if not content or not content.strip(): raise ValueError("Muse Spark returned an empty response.")
    return content


def lira_run_llm_investigation(investigation: LIRAInvestigation, verbose: bool = False) -> dict:
    max_decisions = investigation.remaining_analyses + 1
    trace = []
    def fail(message):
        investigation.status = "FAILED"
        investigation.final_conclusion = "Investigation incomplete: " + message + " Review the available evidence before drawing conclusions."
    for step in range(max_decisions):
        if investigation.status != "IN_PROGRESS": break
        try:
            decision = lira_parse_agent_decision(lira_call_muse_spark(investigation), investigation)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            fail(f"LLM or validation error ({message}).")
            return {"status": investigation.status, "error": message, "final_conclusion": investigation.final_conclusion, "analyses_used": investigation.analyses_used, "analyses_remaining": investigation.remaining_analyses, "trace": trace, "investigation": investigation.to_dict()}
        if not decision.get("valid"):
            reason = decision.get("reason", "Unknown validation error.")
            fail(f"Invalid LLM decision ({reason}).")
            return {"status": investigation.status, "error": reason, "final_conclusion": investigation.final_conclusion, "analyses_used": investigation.analyses_used, "analyses_remaining": investigation.remaining_analyses, "trace": trace, "investigation": investigation.to_dict()}
        trace.append({"step": step + 1, "decision": decision})
        if decision["decision"] == "stop":
            investigation.stop(decision["conclusion"])
            break
        action_result = lira_run_action({"tool": decision["tool"], "reason": decision["reason"]}, investigation)
        trace[-1]["action_result"] = action_result
        history = investigation.action_history
        outcome = history[-1].get("outcome", "") if history else ""
        if not action_result.get("executed") or str(outcome).startswith("ERROR"):
            fail("An investigation tool failed.")
            break
    if investigation.status == "IN_PROGRESS":
        investigation.stop("Investigation stopped at its decision limit. Available evidence may be insufficient for a definitive conclusion.")
    return {"status": investigation.status, "final_conclusion": investigation.final_conclusion, "analyses_used": investigation.analyses_used, "analyses_remaining": investigation.remaining_analyses, "trace": trace, "investigation": investigation.to_dict()}


def lira_render_markdown_report(investigation: LIRAInvestigation, result: dict, detection: dict) -> str:
    history_by_tool = {x.get("tool"): x for x in investigation.action_history if isinstance(x, dict)}
    history = [f"{i}. **`{x.get('tool', 'Unknown')}`** — {x.get('outcome', 'UNKNOWN')}\n   - Reason: {x.get('reason', 'No reason recorded.')}" for i, x in enumerate(investigation.action_history, 1)] or ["No action history was recorded."]
    evidence = []
    for i, item in enumerate(investigation.evidence, 1):
        tool = item.get("tool", "Unknown")
        evidence.append(f"### Analysis {i} — `{tool}`\n\n- **Execution status:** {history_by_tool.get(tool, {}).get('outcome', 'RECORDED')}\n- **Timestamp (UTC):** {item.get('timestamp', 'Not recorded')}\n- **Reason:** {history_by_tool.get(tool, {}).get('reason', 'No reason recorded.')}\n\n```json\n{json.dumps(item.get('result', {}), indent=2, ensure_ascii=False, default=str)}\n```\n")
    confidence = float(detection.get("confidence", 0.0))
    conclusion = result.get("final_conclusion") or investigation.final_conclusion or "No final conclusion available."
    return f"""# LIRA — Network Security Investigation Report

> **ML detects. LLM investigates, explains and guides.**

## 1. Executive Summary

- **Investigation ID:** `{investigation.investigation_id}`
- **Status:** {result.get('status', investigation.status)}
- **Predicted traffic class:** `{detection.get('prediction', 'UNKNOWN')}`
- **Random Forest confidence:** {confidence:.1%}
- **Additional analyses used:** {result.get('analyses_used', investigation.analyses_used)}
- **Analyses remaining:** {result.get('analyses_remaining', investigation.remaining_analyses)}
- **Report generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

### Preliminary assessment

The model classified this flow as **{detection.get('prediction', 'UNKNOWN')}**. This is a model prediction, not independent proof that a real-world attack occurred.

## 2. Investigation History

{chr(10).join(history)}

## 3. Investigation Evidence

{chr(10).join(evidence) if evidence else 'No detailed evidence was recorded.'}

## 4. Final Assessment

{conclusion}

## 5. Recommended Operational Follow-up

1. Check relevant server, authentication, and network logs for corroborating evidence.
2. Verify whether the activity matches legitimate administrative or testing activity.
3. Review the alert with a network or security administrator before taking disruptive action.
4. Do not treat model confidence or similarity to reference flows as definitive proof of compromise.

## 6. Limitations

- The investigation concerns a dataset record, not live production traffic.
- Random Forest probabilities may not be calibrated.
- Similarity to reference flows does not independently confirm an attack.
- No independent operational logs are available to confirm compromise.

---
*Generated by LIRA (Learning Intrusion Reasoning Agent). This report supports security triage and does not replace human verification.*
"""
