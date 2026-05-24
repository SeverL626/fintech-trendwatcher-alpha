OPENROUTER_EMBEDDINGS_ENDPOINT = "https://openrouter.ai/api/v1/embeddings"
OPENROUTER_EMBEDDING_MODEL = "openai/text-embedding-3-large"
OPENROUTER_TIMEOUT_SECONDS = 60
OPENROUTER_MAX_RETRIES = 3
OPENROUTER_RETRY_SECONDS = 20
OPENROUTER_EMBEDDING_REQUEST_DELAY_SECONDS = 0

DEFAULT_SIMILARITY_THRESHOLD = 0.62
DUPLICATE_LOOKBACK_DAYS = 3
DEFAULT_EMBEDDING_BATCH_SIZE = 100

DEFAULT_PCA_ENABLED = True
DEFAULT_PCA_REMOVE_COMPONENTS = 1
DEFAULT_PCA_WHITEN = False
DEFAULT_PCA_MIN_SIGNALS = 20
DEFAULT_PCA_EPSILON = 1e-6
DEFAULT_PCA_MAX_FIT_SIGNALS = None
DEFAULT_PCA_RANDOM_SEED = 42
PCA_PROJECTION_BLOCK_SIZE = 256
SIMILARITY_SEARCH_MODE = "streaming_row_dot"

STATUS_LLM_DONE = "llm_done"
STATUS_EMBEDDING_DONE = "embedding_done"
STATUS_MODELS_DONE = "models_done"
STATUS_DUPLICATE = "duplicate"
STATUS_DEDUP_DONE = "dedup_done"
STATUS_ERROR = "error"

FINTECH_KEYWORDS = (
    "банк",
    "банков",
    "финтех",
    "платеж",
    "перевод",
    "карта",
    "кредит",
    "вклад",
    "цб",
    "регулятор",
    "мошен",
    "кибер",
    "санкц",
    "бирж",
    "инвест",
    "ставк",
    "инфляц",
    "биометр",
    "идентификац",
    "open banking",
    "bnpl",
    "swift",
)

SCALE_KEYWORDS = (
    "массов",
    "крупн",
    "миллион",
    "млрд",
    "федераль",
    "системн",
    "рынок",
    "все банк",
    "клиент",
)

URGENCY_KEYWORDS = (
    "сроч",
    "сегодня",
    "завтра",
    "дедлайн",
    "вступ",
    "запрет",
    "обяз",
    "атака",
    "сбой",
    "санкц",
)

RIGIDITY_KEYWORDS = (
    "закон",
    "требован",
    "штраф",
    "обяз",
    "запрет",
    "цб",
    "регулятор",
    "лиценз",
    "санкц",
)
