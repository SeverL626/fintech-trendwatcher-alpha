import json
import warnings
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np


MODEL_DIR = Path(__file__).resolve().parent / "hotness_models"
FINTECH_MODEL_FILE = MODEL_DIR / "fintech_filter_prod.pkl"
FEATURE_MODEL_FILES = {
    "scale_score": MODEL_DIR / "model_scale_prod.pkl",
    "urgency_score": MODEL_DIR / "model_urgency_prod.pkl",
    "rigidity_score": MODEL_DIR / "model_rigidity_prod.pkl",
}
HOTNESS_MODEL_FILE = MODEL_DIR / "hotness_model_prod.pkl"
EXPECTED_EMBEDDING_DIM = 3072
HOTNESS_PLACEHOLDER = -1.0


def predict_signal_models(embedding):
    vector = normalize_embedding(embedding)
    if vector is None:
        return {
            "is_fintech": False,
            "scale_score": None,
            "urgency_score": None,
            "rigidity_score": None,
            "hotness": HOTNESS_PLACEHOLDER,
        }

    fintech_model = load_fintech_model()
    probability = predict_fintech_probability(fintech_model, vector)
    threshold = float(fintech_model["threshold"])
    is_fintech = probability >= threshold
    if not is_fintech:
        return {
            "is_fintech": False,
            "scale_score": None,
            "urgency_score": None,
            "rigidity_score": None,
            "hotness": HOTNESS_PLACEHOLDER,
            "fintech_probability": round_clip(probability),
        }

    features = {}
    feature_models = load_feature_models()
    x = vector.reshape(1, -1)
    for field, model in feature_models.items():
        prediction = float(model.predict(x)[0])
        features[field] = round_clip(prediction)

    return {
        "is_fintech": True,
        "scale_score": features.get("scale_score"),
        "urgency_score": features.get("urgency_score"),
        "rigidity_score": features.get("rigidity_score"),
        "hotness": HOTNESS_PLACEHOLDER,
        "fintech_probability": round_clip(probability),
    }


def normalize_embedding(embedding):
    if not isinstance(embedding, (list, tuple, np.ndarray)):
        return None
    try:
        vector = np.asarray(embedding, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if vector.ndim != 1 or vector.size != EXPECTED_EMBEDDING_DIM:
        return None
    return vector


def predict_fintech_probability(model_artifact, vector):
    pipeline = model_artifact["model"]
    probabilities = pipeline.predict_proba(vector.reshape(1, -1))[0]
    return float(probabilities[1])


def round_clip(value):
    return round(float(np.clip(value, 0.0, 5.0)), 2)


def predict_hotness_score(scale_score, urgency_score, rigidity_score, duplicate_count=1, authority_score=0.5):
    artifact = load_hotness_model()
    features = artifact["features"]
    values = {
        "scale_score": coerce_float(scale_score),
        "urgency_score": coerce_float(urgency_score),
        "rigidity_score": coerce_float(rigidity_score),
        "dup_count_norm": float(np.log1p(max(1, int(duplicate_count or 1)))),
        "auth_score": coerce_float(authority_score, 0.5),
        "source_authority": coerce_float(authority_score, 0.5),
    }
    if any(values.get(feature) is None for feature in features):
        return HOTNESS_PLACEHOLDER

    vector = np.array([[values[feature] for feature in features]], dtype=np.float32)
    scaled = artifact["scaler"].transform(vector)
    if "model" in artifact and hasattr(artifact["model"], "predict"):
        prediction = float(artifact["model"].predict(scaled)[0])
    else:
        prediction = float(np.dot(scaled, artifact["weights"])[0])
    return round_clip(prediction)


def coerce_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def load_fintech_model():
    if not FINTECH_MODEL_FILE.exists():
        raise FileNotFoundError(f"Fintech model file not found: {FINTECH_MODEL_FILE}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        artifact = joblib.load(FINTECH_MODEL_FILE)
    if not isinstance(artifact, dict) or "model" not in artifact or "threshold" not in artifact:
        raise ValueError(f"Invalid fintech model artifact: {FINTECH_MODEL_FILE}")
    return artifact


@lru_cache(maxsize=1)
def load_feature_models():
    models = {}
    for field, path in FEATURE_MODEL_FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"Feature model file not found: {path}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            models[field] = joblib.load(path)
    return models


@lru_cache(maxsize=1)
def load_hotness_model():
    if not HOTNESS_MODEL_FILE.exists():
        raise FileNotFoundError(f"Hotness model file not found: {HOTNESS_MODEL_FILE}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        artifact = joblib.load(HOTNESS_MODEL_FILE)
    if not isinstance(artifact, dict):
        raise ValueError(f"Invalid hotness model artifact: {HOTNESS_MODEL_FILE}")
    required = {"scaler", "features"}
    missing = required - set(artifact)
    if missing:
        raise ValueError(f"Invalid hotness model artifact, missing: {', '.join(sorted(missing))}")
    if "model" not in artifact and "weights" not in artifact:
        raise ValueError("Invalid hotness model artifact, missing: model or weights")
    if "weights" in artifact:
        artifact["weights"] = np.asarray(artifact["weights"], dtype=np.float32)
    return artifact


def get_hotness_model_status():
    hotness_status = describe_model_file(HOTNESS_MODEL_FILE)
    if hotness_status.get("exists"):
        try:
            artifact = load_hotness_model()
            hotness_status.update({
                "status": "ready",
                "features": list(artifact["features"]),
                "kind": "sklearn_model" if "model" in artifact else "weights",
            })
        except Exception as error:
            hotness_status.update({
                "status": "error",
                "error": str(error),
            })
    return {
        "fintech_model": describe_model_file(FINTECH_MODEL_FILE),
        "feature_models": {
            field: describe_model_file(path)
            for field, path in FEATURE_MODEL_FILES.items()
        },
        "expected_embedding_dim": EXPECTED_EMBEDDING_DIM,
        "hotness_model": hotness_status,
    }


def describe_model_file(path):
    if not path.exists():
        return {"exists": False, "path": str(path)}
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": path.stat().st_size,
    }


def parse_embedding_json(value):
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(parsed, dict):
        return parsed.get("embedding")
    if isinstance(parsed, list):
        return parsed
    return None
