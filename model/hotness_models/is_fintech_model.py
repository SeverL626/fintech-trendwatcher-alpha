import pandas as pd
import numpy as np
import logging
import joblib
import json
import ast
import os
from openai import OpenAI
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.feature_selection import VarianceThreshold
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import f1_score, classification_report

# Исправленная инициализация логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger(__name__)

# ================= КОНФИГУРАЦИЯ =================
API_KEY = "sk-ne1f95MEV0C6rrIlZ0e6rR1y2n6l8HOy"
BASE_URL = "https://api.proxyapi.ru/openai/v1"
MODEL_NAME = "text-embedding-3-large"

MODEL_FILE = "fintech_filter_prod.pkl"
TRAIN_CSV_PATH = "/kaggle/input/datasets/alonix/marked-data-signals/signals_202605221954_data_export_labeled-4.csv"  # Файл для обучения
INFERENCE_CSV_PATH = "/kaggle/working/signals_202605221954_data_export_labeled-4.csv"  # Файл для продакшена


# ================================================

# --- УТИЛИТЫ ---
def parse_csv_embedding(val):
    """
    Парсит JSON-строку из CSV, извлекает словарь
    и забирает сам вектор по ключу 'embedding'.
    """
    if pd.isna(val) or val == "":
        return None

    # Если это уже словарь (бывает при повторных циклах в памяти)
    if isinstance(val, dict):
        return val.get("embedding")

    if isinstance(val, str):
        try:
            # Пробуем распарсить строку в словарь
            data = json.loads(val.strip())
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(val.strip())
            except (ValueError, SyntaxError):
                return None

        # Извлекаем сам вектор, если получили словарь
        if isinstance(data, dict):
            return data.get("embedding")  # Возвращает список чисел или None
        elif isinstance(data, list):
            return data  # На случай, если там лежал чистый массив

    return None


def format_embedding_for_csv(val):
    """Сохраняет вектор обратно в структуру JSON-словаря для совместимости с БД."""
    if isinstance(val, (list, np.ndarray)):
        structure = {
            "model": MODEL_NAME,
            "embedding": list(val)
        }
        return json.dumps(structure)
    return val


def get_embeddings(texts: list, client: OpenAI, model: str, batch_size=50) -> list:
    clean_texts = [(str(t) if pd.notna(t) else "").strip()[:8000] for t in texts]
    embs = []

    for i in range(0, len(clean_texts), batch_size):
        batch = clean_texts[i:i + batch_size]
        if not any(batch):
            dim = 3072 if "large" in model else 1536
            embs.extend([np.zeros(dim, dtype=np.float32).tolist() for _ in batch])
            continue

        try:
            resp = client.embeddings.create(input=batch, model=model, encoding_format="float")
            embs.extend([d.embedding for d in resp.data])
        except Exception as e:
            logger.error(f"API Error (batch {i}): {e}")
            dim = 3072 if "large" in model else 1536
            embs.extend([np.zeros(dim, dtype=np.float32).tolist() for _ in batch])

    return embs


# --- КЛАССЫ МОДЕЛИ ---
from sklearn.linear_model import LogisticRegressionCV


class FintechModelTrainer:
    def __init__(self, pca_components=80):
        self.pipeline = Pipeline([
            ("var_filter", VarianceThreshold(threshold=1e-4)),
            ("pca", PCA(n_components=pca_components, random_state=42, svd_solver='full')),
            ("scaler", StandardScaler(with_mean=False)),
            # Кросс-валидация для подбора параметра 'C' (обратная сила регуляризации)
            ("clf", LogisticRegressionCV(
                Cs=10, cv=5, penalty='l2', class_weight='balanced',
                max_iter=2000, random_state=42, solver='lbfgs'
            ))
        ])
        self.optimal_threshold = 0.5

    def fit_and_optimize(self, X: np.ndarray, y: np.ndarray):
        # Стратифицированное разбиение для сохранения баланса классов
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.20, random_state=42, stratify=y
        )

        self.pipeline.fit(X_train, y_train)

        # Лучший параметр C, найденный моделью
        best_c = self.pipeline.named_steps['clf'].C_[0]
        logger.info(f"Оптимальный параметр C (обратная регуляризация): {best_c:.4f}")

        probs = self.pipeline.predict_proba(X_test)[:, 1]

        best_f1 = 0
        thresholds = np.arange(0.3, 0.85, 0.05)
        for t in thresholds:
            preds = (probs >= t).astype(int)
            score = f1_score(y_test, preds, zero_division=0)
            if score > best_f1:
                best_f1 = score
                self.optimal_threshold = t

        logger.info(f"Оптимальный порог: {self.optimal_threshold:.2f} (F1 на тесте: {best_f1:.3f})")

        final_preds = (probs >= self.optimal_threshold).astype(int)
        logger.info("\n" + classification_report(y_test, final_preds))

    def save(self, filepath: str):
        artifact = {
            'model': self.pipeline,
            'threshold': self.optimal_threshold
        }
        joblib.dump(artifact, filepath)
        logger.info(f"Модель сохранена в {filepath}")


class FintechFilterProd:
    def __init__(self, model_path=MODEL_FILE):
        artifact = joblib.load(model_path)
        self.pipeline = artifact['model']
        self.threshold = artifact['threshold']
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    def process_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df['embedding_json'] = df.get('embedding_json', pd.Series([None] * len(df))).apply(parse_csv_embedding)
        missing_mask = df["embedding_json"].isnull()

        if missing_mask.any():
            logger.info(f"Получение {missing_mask.sum()} новых эмбеддингов...")
            new_texts = df.loc[missing_mask, "summary"].tolist()
            new_embs = get_embeddings(new_texts, self.client, MODEL_NAME)
            df.loc[missing_mask, "embedding_json"] = pd.Series(new_embs, index=df[missing_mask].index, dtype=object)

        valid_mask = df["embedding_json"].apply(lambda x: isinstance(x, (list, np.ndarray)))

        if valid_mask.any():
            X_prod = np.stack(df.loc[valid_mask, "embedding_json"].values)
            probs = self.pipeline.predict_proba(X_prod)[:, 1]

            df.loc[valid_mask, "is_fintech"] = (probs >= self.threshold).astype(int)

        return df


# --- ФУНКЦИИ ЗАПУСКА ДЛЯ CSV ---
def execute_training(csv_path=TRAIN_CSV_PATH, sep=';'):
    logger.info("Запуск подготовки данных и обучения...")
    df = pd.read_csv(csv_path, sep=sep)

    df['embedding_json'] = df.get('embedding_json', pd.Series([None] * len(df))).apply(parse_csv_embedding)

    missing_mask = df['embedding_json'].isnull()
    if missing_mask.any():
        logger.info("Докачиваем отсутствующие эмбеддинги для трейна...")
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        new_texts = df.loc[missing_mask, "summary"].tolist()
        df.loc[missing_mask, "embedding_json"] = pd.Series(get_embeddings(new_texts, client, MODEL_NAME),
                                                           index=df[missing_mask].index, dtype=object)

        # РЕШЕНИЕ: Сохраняем копию в /kaggle/working/, так как input защищен от записи
        df_save = df.copy()
        df_save["embedding_json"] = df_save["embedding_json"].apply(format_embedding_for_csv)

        # Выделяем имя файла из пути и сохраняем в текущую рабочую директорию
        output_name = os.path.basename(csv_path)
        df_save.to_csv(output_name, sep=sep, index=False)
        logger.info(f"Обновленный трейн-файл с эмбеддингами сохранен в: {output_name}")

    df_clean = df.dropna(subset=["embedding_json", "is_fintech"])
    X = np.stack(df_clean["embedding_json"].values)
    y = df_clean["is_fintech"].astype(int).values

    trainer = FintechModelTrainer()
    trainer.fit_and_optimize(X, y)
    trainer.save(MODEL_FILE)


def execute_inference(csv_path=INFERENCE_CSV_PATH, sep=';'):
    logger.info("Запуск инференса на рабочем датасете...")
    df = pd.read_csv(csv_path, sep=sep)

    prod_filter = FintechFilterProd(model_path=MODEL_FILE)
    df_processed = prod_filter.process_signals(df)

    df_processed["embedding_json"] = df_processed["embedding_json"].apply(format_embedding_for_csv)

    # Сохраняем результат в рабочую директорию, а не обратно в input
    output_name = "processed_" + os.path.basename(csv_path)
    df_processed.to_csv(output_name, sep=sep, index=False)
    logger.info(f"Результат инференса сохранен в: {output_name}")


# ================= ТОЧКА ВХОДА =================
if __name__ == "__main__":
    # Убедись, что разделитель CSV совпадает с твоим (обычно ';' или ',')

    # Шаг 1: Запуск обучения (раскомментировать для переобучения модели)
    execute_training(csv_path=TRAIN_CSV_PATH, sep=';')

    # Шаг 2: Запуск в продакшене (работа с новыми данными)
    # execute_inference(csv_path=INFERENCE_CSV_PATH, sep=';')
    pass