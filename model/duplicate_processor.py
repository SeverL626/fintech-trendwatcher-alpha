import json
import os
import re
import time
from datetime import datetime, timedelta

import numpy as np
import requests

try:
    from back.init_db import DB_PATH, connect_db
except ModuleNotFoundError:
    from init_db import DB_PATH, connect_db


OPENROUTER_EMBEDDINGS_ENDPOINT = "https://openrouter.ai/api/v1/embeddings"
OPENROUTER_EMBEDDING_MODEL = "openai/text-embedding-3-large"
OPENROUTER_TIMEOUT_SECONDS = 60
OPENROUTER_MAX_RETRIES = 3
OPENROUTER_RETRY_SECONDS = 20
OPENROUTER_EMBEDDING_REQUEST_DELAY_SECONDS = 0
DEFAULT_SIMILARITY_THRESHOLD = 0.62
DUPLICATE_LOOKBACK_DAYS = 3
DEFAULT_BATCH_SIZE = 100
DEFAULT_PCA_ENABLED = True
DEFAULT_PCA_REMOVE_COMPONENTS = 1
DEFAULT_PCA_WHITEN = False
DEFAULT_PCA_MIN_SIGNALS = 20
DEFAULT_PCA_EPSILON = 1e-6
DEFAULT_PCA_MAX_FIT_SIGNALS = None
DEFAULT_PCA_RANDOM_SEED = 42
PCA_PROJECTION_BLOCK_SIZE = 256
SIMILARITY_SEARCH_MODE = "streaming_row_dot"
DUPLICATE_PREFIX = "DUBLICATE OF "
CURRENCY_RATES_PHRASE = "курсы валют"
SPECIAL_SUMMARIES = {
    "Вышла таблица.",
    "Вышел отчёт.",
    "Вышел отчет.",
}


def process_signal_duplicates(
    db_path=DB_PATH,
    similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD,
    batch_size=DEFAULT_BATCH_SIZE,
):
    ensure_duplicates_configured()
    started_at = datetime.now()

    with connect_db(db_path) as db:
        signals = load_dedup_signals(db)
        raw_news_by_id = load_raw_news_by_id(db, collect_raw_news_ids(signals))

        for signal in signals:
            enrich_signal_metadata(signal, raw_news_by_id)

        signals_by_id = {signal["id"]: signal for signal in signals}
        candidate_signals = [
            signal
            for signal in signals
            if not signal.get("is_duplicate")
        ]
        eligible_signals = [
            signal
            for signal in candidate_signals
            if is_dedup_eligible(signal)
        ]
        hydrate_signal_embeddings(eligible_signals)
        excluded_signals = len(candidate_signals) - len(eligible_signals)
        candidates_to_embed = [
            signal
            for signal in eligible_signals
            if not signal.get("embedding")
        ]

        embeddings_created, embedding_usage = embed_and_store_signals(db, candidates_to_embed, batch_size)

        all_candidates = [
            signal
            for signal in eligible_signals
            if signal.get("embedding")
        ]
        candidate_ids = {signal["id"] for signal in all_candidates}

        duplicate_groups, pca_summary = find_duplicate_groups(all_candidates, candidate_ids, similarity_threshold)
        merged_sources = 0
        duplicates_marked = 0
        for base_id, duplicate_ids, similarity in duplicate_groups:
            base_signal = signals_by_id.get(base_id)
            if not base_signal:
                continue

            duplicate_signals = [
                signals_by_id[duplicate_id]
                for duplicate_id in duplicate_ids
                if duplicate_id in signals_by_id and not signals_by_id[duplicate_id].get("is_duplicate")
            ]
            if not duplicate_signals:
                continue

            merge_duplicate_sources(db, base_signal, duplicate_signals)
            mark_duplicate_signals(db, base_signal, duplicate_signals)
            merged_sources += len(duplicate_signals)
            duplicates_marked += len(duplicate_signals)

            for duplicate_signal in duplicate_signals:
                duplicate_signal["is_duplicate"] = True
                duplicate_signal["draft"] = f"{DUPLICATE_PREFIX}{base_signal['base_raw_news_id']}"

        checked_signals = [signal for signal in eligible_signals if not signal.get("is_duplicate")]
        mark_signals_dedup_checked(db, checked_signals)

    finished_at = datetime.now()
    return {
        "processed_signals": len(eligible_signals),
        "candidate_signals": len(candidate_signals),
        "excluded_signals": excluded_signals,
        "compared_signals": len(all_candidates),
        "embedded_signals": embeddings_created,
        "duplicates_marked": duplicates_marked,
        "merged_sources": merged_sources,
        "similarity_threshold": similarity_threshold,
        "pair_window_days": DUPLICATE_LOOKBACK_DAYS,
        "embedding_model": OPENROUTER_EMBEDDING_MODEL,
        "pca": pca_summary,
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "openrouter": embedding_usage,
    }


def load_dedup_signals(db):
    rows = db.execute("""
        SELECT id, headline, hotness, why_now, summary, sources, draft
        FROM signals
        WHERE summary IS NOT NULL
          AND TRIM(summary) != ''
          AND (draft IS NULL OR draft NOT LIKE ?)
        ORDER BY id ASC
    """, (f"{DUPLICATE_PREFIX}%",)).fetchall()

    signals = []
    for row in rows:
        signal = dict(row)
        draft = signal.get("draft") or ""
        signal["source_ids"] = parse_source_ids(signal.get("sources"))
        signal["embedding"] = None
        signal["dedup_checked"] = '"dedup_checked_at"' in draft
        signal["is_duplicate"] = is_duplicate_draft(signal.get("draft"))
        signals.append(signal)
    return signals


def hydrate_signal_embeddings(signals):
    for signal in signals:
        draft_data = parse_draft_json(signal.get("draft"))
        if not draft_data:
            continue

        embedding = draft_data.get("embedding")
        if is_valid_embedding(embedding):
            signal["embedding"] = embedding
        signal["dedup_checked"] = bool(draft_data.get("dedup_checked_at"))


def is_valid_embedding(value):
    return isinstance(value, list) and bool(value)


def is_dedup_eligible(signal):
    if normalize_hotness(signal.get("hotness")) <= 1:
        return False
    if is_report_signal(signal):
        return False
    return bool(clean_text(signal.get("summary")))


def is_report_signal(signal):
    why_now = clean_text(signal.get("why_now")).casefold()
    summary = clean_text(signal.get("summary"))
    summary_lower = summary.casefold()
    return (
        why_now in {"отчёт", "отчет", "--"}
        or summary in SPECIAL_SUMMARIES
        or summary_lower.startswith("вышел отч")
        or summary_lower.startswith("вышла таблиц")
    )


def normalize_hotness(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def collect_raw_news_ids(signals):
    raw_news_ids = set()
    for signal in signals:
        raw_news_ids.update(signal.get("source_ids") or [])
    return raw_news_ids


def load_raw_news_by_id(db, raw_news_ids):
    if not raw_news_ids:
        return {}

    result = {}
    ids = sorted(raw_news_ids)
    for chunk in chunked(ids, 500):
        placeholders = ",".join("?" for _ in chunk)
        rows = db.execute(f"""
            SELECT id, published_at, parsed_at
            FROM raw_news
            WHERE id IN ({placeholders})
        """, chunk).fetchall()
        for row in rows:
            result[row["id"]] = dict(row)
    return result


def enrich_signal_metadata(signal, raw_news_by_id):
    source_ids = signal.get("source_ids") or []
    raw_rows = [raw_news_by_id[raw_id] for raw_id in source_ids if raw_id in raw_news_by_id]
    dated_raw_ids = []
    for raw_row in raw_rows:
        event_at = parse_datetime(raw_row.get("published_at") or raw_row.get("parsed_at"))
        if event_at:
            dated_raw_ids.append((event_at, raw_row["id"]))

    if dated_raw_ids:
        dated_raw_ids.sort(key=lambda item: (item[0], item[1]))
        signal["event_at"] = dated_raw_ids[0][0]
        signal["base_raw_news_id"] = dated_raw_ids[0][1]
    else:
        signal["event_at"] = None
        signal["base_raw_news_id"] = min(source_ids) if source_ids else signal["id"]


def embed_and_store_signals(db, signals, batch_size):
    if not signals:
        return 0, make_empty_openrouter_usage()

    usage_items = []
    embedded_count = 0
    safe_batch_size = max(1, int(batch_size or DEFAULT_BATCH_SIZE))
    for batch in chunked(signals, safe_batch_size):
        texts = [build_embedding_text(signal) for signal in batch]
        embeddings, usage = fetch_openrouter_embeddings(texts)
        usage_items.append(usage)
        for signal, embedding in zip(batch, embeddings):
            embedding_list = [float(value) for value in embedding]
            signal["embedding"] = embedding_list
            store_signal_embedding(db, signal, embedding_list)
            embedded_count += 1
        db.commit()
        sleep_between_embedding_requests()

    return embedded_count, summarize_openrouter_usage(usage_items)


def build_embedding_text(signal):
    headline = clean_text(signal.get("headline"))
    summary = clean_text(signal.get("summary"))
    return "\n".join(part for part in (headline, summary) if part) or " "


def fetch_openrouter_embeddings(texts):
    api_key = os.getenv("OPENROUTER_API_KEY")
    payload = {
        "model": OPENROUTER_EMBEDDING_MODEL,
        "input": [text if text and text.strip() else " " for text in texts],
    }

    last_response = None
    for attempt in range(OPENROUTER_MAX_RETRIES + 1):
        response = requests.post(
            OPENROUTER_EMBEDDINGS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://127.0.0.1:5000"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "Fintech Trendwatcher"),
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT_SECONDS,
        )
        last_response = response
        if response.status_code != 429:
            break
        if attempt >= OPENROUTER_MAX_RETRIES:
            break
        time.sleep(OPENROUTER_RETRY_SECONDS * (attempt + 1))

    if last_response is None:
        raise RuntimeError("OpenRouter embeddings API did not return a response")
    if last_response.status_code >= 400:
        raise RuntimeError(sanitize_error_message(format_openrouter_error(last_response)))

    data = last_response.json()
    embeddings = [
        item.get("embedding") or []
        for item in sorted(data.get("data", []), key=lambda item: item.get("index", 0))
    ]
    if len(embeddings) != len(texts) or any(not embedding for embedding in embeddings):
        raise RuntimeError("OpenRouter embeddings API returned an invalid embeddings payload")

    return embeddings, data.get("usage") or {}


def store_signal_embedding(db, signal, embedding):
    draft_data = parse_draft_json(signal.get("draft"))
    if signal.get("draft") and not draft_data:
        draft_data["previous_draft"] = clean_text(signal.get("draft"))
    draft_data["embedding_model"] = OPENROUTER_EMBEDDING_MODEL
    draft_data["embedding"] = embedding
    draft_data["dedup_processed_at"] = datetime.now().isoformat(timespec="seconds")
    serialized_draft = json.dumps(draft_data, ensure_ascii=False)
    signal["draft"] = serialized_draft
    db.execute(
        "UPDATE signals SET draft = ? WHERE id = ?",
        (serialized_draft, signal["id"]),
    )


def find_duplicate_groups(signals, new_ids, similarity_threshold):
    signals_with_embeddings = [signal for signal in signals if signal.get("embedding")]
    if not signals_with_embeddings or not new_ids:
        return [], make_pca_summary(DEFAULT_PCA_ENABLED, False, len(signals_with_embeddings), "no_embeddings_or_new_ids")

    groups, pca_summary = find_duplicate_groups_in_bucket(
        signals_with_embeddings,
        new_ids,
        similarity_threshold,
    )

    return groups, make_duplicate_search_summary(signals_with_embeddings, pca_summary)


def make_duplicate_search_summary(signals, pca_summary):
    return {
        "enabled": DEFAULT_PCA_ENABLED,
        "applied": bool(pca_summary.get("applied")),
        "reason": "global_dataset_pair_window",
        "signals": len(signals),
        "pair_window_days": DUPLICATE_LOOKBACK_DAYS,
        "similarity_mode": SIMILARITY_SEARCH_MODE,
        "full_similarity_matrix": False,
        "pca": pca_summary,
    }


def find_duplicate_groups_in_bucket(signals_with_embeddings, new_ids, similarity_threshold):
    embeddings = np.array([signal["embedding"] for signal in signals_with_embeddings], dtype=np.float32)
    normalized, pca_summary = prepare_duplicate_vectors(embeddings)
    pca_summary["similarity_mode"] = SIMILARITY_SEARCH_MODE
    pca_summary["full_similarity_matrix"] = False

    index_by_id = {signal["id"]: index for index, signal in enumerate(signals_with_embeddings)}
    processed_ids = set()
    groups = []

    for signal in signals_with_embeddings:
        signal_id = signal["id"]
        if signal_id not in new_ids or signal_id in processed_ids:
            continue

        signal_index = index_by_id[signal_id]
        similarities = normalized @ normalized[signal_index]
        similar_indices = np.flatnonzero(similarities >= similarity_threshold)
        candidates = [
            signals_with_embeddings[index]
            for index in similar_indices
            if is_inside_pair_window(signal, signals_with_embeddings[index], DUPLICATE_LOOKBACK_DAYS)
        ]
        if len(candidates) <= 1:
            processed_ids.add(signal_id)
            continue

        candidates.sort(key=get_duplicate_base_sort_key(candidates))
        base_signal = candidates[0]
        duplicate_signals = [candidate for candidate in candidates if candidate["id"] != base_signal["id"]]
        if not duplicate_signals:
            processed_ids.add(signal_id)
            continue

        base_index = index_by_id[base_signal["id"]]
        base_similarities = normalized @ normalized[base_index]
        min_similarity = min(
            float(base_similarities[index_by_id[duplicate_signal["id"]]])
            for duplicate_signal in duplicate_signals
        )
        groups.append((
            base_signal["id"],
            [duplicate_signal["id"] for duplicate_signal in duplicate_signals],
            round(min_similarity, 6),
        ))
        processed_ids.update(candidate["id"] for candidate in candidates)

    return groups, pca_summary


def prepare_duplicate_vectors(embeddings):
    pca_enabled = DEFAULT_PCA_ENABLED
    if not pca_enabled:
        return normalize_vectors(embeddings), make_pca_summary(False, False, len(embeddings), "disabled")

    cleaned, pca_summary = remove_pca_components(
        embeddings,
        remove_components=DEFAULT_PCA_REMOVE_COMPONENTS,
        whiten=DEFAULT_PCA_WHITEN,
        min_signals=DEFAULT_PCA_MIN_SIGNALS,
        epsilon=DEFAULT_PCA_EPSILON,
    )
    return normalize_vectors(cleaned), pca_summary


def remove_pca_components(embeddings, remove_components, whiten, min_signals, epsilon):
    signal_count, dimension_count = embeddings.shape
    requested_components = max(0, int(remove_components or 0))
    min_signals = max(2, int(min_signals or 0))
    max_components = max(0, min(signal_count - 1, dimension_count, requested_components))

    if signal_count < min_signals:
        return embeddings, make_pca_summary(True, False, signal_count, "not_enough_signals")
    if max_components <= 0:
        return embeddings, make_pca_summary(True, False, signal_count, "no_components_to_remove")

    centered = embeddings.astype(np.float32, copy=False)
    mean = np.mean(centered, axis=0, keepdims=True, dtype=np.float64).astype(np.float32)
    centered -= mean
    fit_matrix = centered
    fit_signal_count = signal_count
    sampled = False
    if DEFAULT_PCA_MAX_FIT_SIGNALS and signal_count > DEFAULT_PCA_MAX_FIT_SIGNALS:
        rng = np.random.default_rng(DEFAULT_PCA_RANDOM_SEED)
        sample_indices = np.sort(
            rng.choice(signal_count, size=DEFAULT_PCA_MAX_FIT_SIGNALS, replace=False)
        )
        fit_matrix = centered[sample_indices]
        fit_signal_count = len(sample_indices)
        sampled = True

    try:
        _, singular_values, principal_axes = np.linalg.svd(fit_matrix, full_matrices=False)
    except np.linalg.LinAlgError:
        return embeddings, make_pca_summary(True, False, signal_count, "svd_failed")

    components = principal_axes[:max_components]
    cleaned = centered
    for start in range(0, signal_count, PCA_PROJECTION_BLOCK_SIZE):
        end = min(start + PCA_PROJECTION_BLOCK_SIZE, signal_count)
        projection = cleaned[start:end] @ components.T
        cleaned[start:end] -= projection @ components

    if whiten:
        remaining_components = principal_axes[max_components:]
        if len(remaining_components):
            remaining_values = singular_values[max_components:]
            for start in range(0, signal_count, PCA_PROJECTION_BLOCK_SIZE):
                end = min(start + PCA_PROJECTION_BLOCK_SIZE, signal_count)
                projected = cleaned[start:end] @ remaining_components.T
                projected = projected / np.maximum(remaining_values, float(epsilon))
                cleaned[start:end] = projected @ remaining_components

    return cleaned.astype(np.float32), make_pca_summary(
        True,
        True,
        signal_count,
        "applied",
        removed_components=max_components,
        whiten=whiten,
        fit_signals=fit_signal_count,
        sampled=sampled,
    )


def normalize_vectors(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vectors = vectors.astype(np.float32, copy=False)
    vectors /= norms.astype(np.float32, copy=False)
    return vectors


def make_pca_summary(
    enabled,
    applied,
    signal_count,
    reason,
    removed_components=0,
    whiten=None,
    fit_signals=None,
    sampled=False,
):
    return {
        "enabled": bool(enabled),
        "applied": bool(applied),
        "reason": reason,
        "signals": signal_count,
        "remove_components": DEFAULT_PCA_REMOVE_COMPONENTS,
        "removed_components": removed_components,
        "whiten": DEFAULT_PCA_WHITEN if whiten is None else bool(whiten),
        "min_signals": DEFAULT_PCA_MIN_SIGNALS,
        "max_fit_signals": DEFAULT_PCA_MAX_FIT_SIGNALS,
        "fit_signals": signal_count if fit_signals is None else int(fit_signals),
        "sampled": bool(sampled),
    }


def signal_sort_key(signal):
    event_at = signal.get("event_at") or datetime.max
    return (event_at, signal.get("base_raw_news_id") or signal["id"], signal["id"])


def get_duplicate_base_sort_key(candidates):
    if is_currency_rates_group(candidates):
        return currency_rates_signal_sort_key
    return signal_sort_key


def is_currency_rates_group(candidates):
    return any(is_currency_rates_signal(candidate) for candidate in candidates)


def is_currency_rates_signal(signal):
    text = " ".join(
        clean_text(signal.get(field))
        for field in ("headline", "why_now", "summary")
    ).casefold()
    return CURRENCY_RATES_PHRASE in text


def currency_rates_signal_sort_key(signal):
    event_at = signal.get("event_at") or datetime.min
    return (datetime.max - event_at, -(signal.get("base_raw_news_id") or signal["id"]), -signal["id"])


def merge_duplicate_sources(db, base_signal, duplicate_signals):
    source_ids = set(base_signal.get("source_ids") or [])
    for duplicate_signal in duplicate_signals:
        source_ids.update(duplicate_signal.get("source_ids") or [])
    merged_sources = ",".join(str(raw_news_id) for raw_news_id in sorted(source_ids))
    db.execute(
        "UPDATE signals SET sources = ? WHERE id = ?",
        (merged_sources, base_signal["id"]),
    )
    base_signal["source_ids"] = sorted(source_ids)
    db.commit()


def mark_duplicate_signals(db, base_signal, duplicate_signals):
    duplicate_draft = f"{DUPLICATE_PREFIX}{base_signal['base_raw_news_id']}"
    for duplicate_signal in duplicate_signals:
        db.execute(
            "UPDATE signals SET draft = ? WHERE id = ?",
            (duplicate_draft, duplicate_signal["id"]),
        )
    db.commit()


def mark_signals_dedup_checked(db, signals):
    checked_at = datetime.now().isoformat(timespec="seconds")
    for signal in signals:
        if signal.get("dedup_checked"):
            continue
        row = db.execute(
            "SELECT draft FROM signals WHERE id = ?",
            (signal["id"],),
        ).fetchone()
        current_draft = row["draft"] if row else signal.get("draft")
        draft_data = parse_draft_json(current_draft)
        if current_draft and not draft_data:
            draft_data["previous_draft"] = clean_text(current_draft)
        draft_data["dedup_checked_at"] = checked_at
        signal["draft"] = json.dumps(draft_data, ensure_ascii=False)
        db.execute(
            "UPDATE signals SET draft = ? WHERE id = ?",
            (signal["draft"], signal["id"]),
        )
    db.commit()


def parse_draft_json(value):
    if not value or is_duplicate_draft(value):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_duplicate_draft(value):
    return str(value or "").strip().startswith(DUPLICATE_PREFIX)


def parse_source_ids(value):
    if value is None or value == "":
        return []
    if isinstance(value, int):
        return [value]

    text = str(value).strip()
    if not text:
        return []
    if re.fullmatch(r"\d+", text):
        return [int(text)]
    if "," in text and not text.startswith("["):
        return [int(part) for part in re.findall(r"\d+", text)]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [int(part) for part in re.findall(r"\d+", text)]

    if isinstance(parsed, int):
        return [parsed]
    if isinstance(parsed, list):
        return [int(item) for item in parsed if str(item).strip().isdigit()]
    if isinstance(parsed, dict):
        return [int(value) for value in parsed.values() if str(value).strip().isdigit()]
    return []


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def is_inside_pair_window(left_signal, right_signal, window_days):
    left_at = left_signal.get("event_at")
    right_at = right_signal.get("event_at")
    if not left_at or not right_at:
        return True
    return abs(left_at - right_at) <= timedelta(days=window_days)


def chunked(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def clean_text(value):
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def sleep_between_embedding_requests():
    if OPENROUTER_EMBEDDING_REQUEST_DELAY_SECONDS > 0:
        time.sleep(OPENROUTER_EMBEDDING_REQUEST_DELAY_SECONDS)


def summarize_openrouter_usage(usage_items):
    return {
        "model": OPENROUTER_EMBEDDING_MODEL,
        "requests_sent": len(usage_items),
        "run_cost": round(sum(get_usage_cost(usage) for usage in usage_items), 8),
        "prompt_tokens": sum(int(usage.get("prompt_tokens") or 0) for usage in usage_items),
        "total_tokens": sum(int(usage.get("total_tokens") or 0) for usage in usage_items),
    }


def make_empty_openrouter_usage():
    return {
        "model": OPENROUTER_EMBEDDING_MODEL,
        "requests_sent": 0,
        "run_cost": 0.0,
        "prompt_tokens": 0,
        "total_tokens": 0,
    }


def get_usage_cost(usage):
    return coerce_float(usage.get("cost")) or coerce_float(usage.get("cost_usd")) or 0.0


def coerce_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_openrouter_error(response):
    try:
        body = response.text
    except Exception:
        body = ""
    return f"OpenRouter embeddings API HTTP {response.status_code}: {body}".strip()


def sanitize_error_message(error):
    message = str(error)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", message)
    return message[:1000]


def ensure_duplicates_configured():
    if not os.getenv("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not set")


if __name__ == "__main__":
    print(json.dumps(process_signal_duplicates(), ensure_ascii=False, indent=2))
