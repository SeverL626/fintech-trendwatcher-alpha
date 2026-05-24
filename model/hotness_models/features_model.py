import pandas as pd
import numpy as np
import logging
import joblib
import json
import ast
import os
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.feature_selection import VarianceThreshold
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_squared_error, mean_absolute_error

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger(__name__)

# ================= КОНФИГУРАЦИЯ =================
MODEL_FILES = {
    'scale_score': 'model_scale_prod.pkl',
    'urgency_score': 'model_urgency_prod.pkl',
    'rigidity_score': 'model_rigidity_prod.pkl'
}


# ================================================

# --- УТИЛИТЫ ---
def parse_csv_embedding(val):
    if pd.isna(val) or val == "":
        return None
    if isinstance(val, dict):
        return val.get("embedding")
    if isinstance(val, str):
        try:
            data = json.loads(val.strip())
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(val.strip())
            except (ValueError, SyntaxError):
                return None
        if isinstance(data, dict):
            return data.get("embedding")
        elif isinstance(data, list):
            return data
    return None


def format_embedding_for_csv(val, model_name="text-embedding-3-large"):
    if isinstance(val, (list, np.ndarray)):
        return json.dumps({"model": model_name, "embedding": list(val)})
    return val


def remap_target_labels(y_series):
    """Переводит старую разметку в новые веса."""
    mapping = {0.0: 0.33, 0.5: 0.66, 1.0: 1.0}
    return y_series.replace(mapping)


# --- ЯДРО РЕГРЕССИИ ---
from sklearn.linear_model import RidgeCV


class FeatureRegressor:
    """Универсальная модель регрессии для признаков финтех-новостей."""

    def __init__(self, pca_components=80):
        self.pipeline = Pipeline([
            ("var_filter", VarianceThreshold(threshold=1e-4)),
            ("pca", PCA(n_components=pca_components, random_state=42, svd_solver='full')),
            ("scaler", StandardScaler(with_mean=False)),
            # Автоматический перебор силы L2-регуляризации на 5 фолдах кросс-валидации
            ("regressor", RidgeCV(alphas=[0.1, 1.0, 10.0, 50.0, 100.0, 500.0], cv=5))
        ])

    def fit(self, X: np.ndarray, y: np.ndarray):
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42)

        self.pipeline.fit(X_train, y_train)

        best_alpha = self.pipeline.named_steps['regressor'].alpha_
        logger.info(f"Оптимальный alpha (L2 регуляризация): {best_alpha}")

        preds_train = self.pipeline.predict(X_train)
        preds_test = self.pipeline.predict(X_test)

        # Вывод метрик для контроля переобучения
        logger.info(
            f"Train MSE: {mean_squared_error(y_train, preds_train):.4f} | Train MAE: {mean_absolute_error(y_train, preds_train):.4f}")
        logger.info(
            f"Test  MSE: {mean_squared_error(y_test, preds_test):.4f} | Test  MAE: {mean_absolute_error(y_test, preds_test):.4f}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        preds = self.pipeline.predict(X)
        return np.clip(preds, 0.33, 1.0)

    def save(self, filepath: str):
        joblib.dump(self.pipeline, filepath)
        logger.info(f"Модель сохранена: {filepath}")

    @classmethod
    def load(cls, filepath: str):
        instance = cls()
        instance.pipeline = joblib.load(filepath)
        return instance


# --- ФУНКЦИИ ОБУЧЕНИЯ И ИНФЕРЕНСА ---
def train_feature_model(train_csv_path: str, feature_name: str, sep=';'):
    """Обучает модель для конкретного признака."""
    logger.info(f"Запуск обучения для признака: {feature_name}")

    if feature_name not in MODEL_FILES:
        raise ValueError(f"Неизвестный признак: {feature_name}")

    df = pd.read_csv(train_csv_path, sep=sep)
    df['embedding_json'] = df['embedding_json'].apply(parse_csv_embedding)

    # Оставляем ТОЛЬКО финтех-новости для обучения
    df_train = df[df['is_fintech'] == 1].copy()
    df_train = df_train.dropna(subset=["embedding_json", feature_name])

    # Перевод таргетов 0->0.33, 0.5->0.66, 1->1
    df_train[feature_name] = remap_target_labels(df_train[feature_name])

    # Фильтрация валидных векторов (3072 размерность)
    valid_mask = df_train["embedding_json"].apply(lambda x: isinstance(x, (list, np.ndarray)) and len(x) == 3072)
    df_clean = df_train[valid_mask]

    if len(df_clean) == 0:
        raise ValueError("После фильтрации не осталось данных для обучения!")

    X = np.stack(df_clean["embedding_json"].values)
    y = df_clean[feature_name].astype(float).values

    model = FeatureRegressor()
    model.fit(X, y)
    model.save(MODEL_FILES[feature_name])


def inference_all_features(csv_path: str, sep=';'):
    """Прогоняет датасет через все три модели признаков для продакшена."""
    logger.info("Запуск полного инференса признаков...")
    df = pd.read_csv(csv_path, sep=sep)

    # Сначала сбрасываем всем признакам 0 (для не финтех новостей)
    for feat in MODEL_FILES.keys():
        df[feat] = 0.0

    df['embedding_json'] = df['embedding_json'].apply(parse_csv_embedding)

    # Выделяем только финтех-новости с валидными эмбеддингами
    fintech_mask = df['is_fintech'] == 1
    valid_embs_mask = df['embedding_json'].apply(lambda x: isinstance(x, (list, np.ndarray)) and len(x) == 3072)
    work_mask = fintech_mask & valid_embs_mask

    if work_mask.any():
        X_prod = np.stack(df.loc[work_mask, "embedding_json"].values)

        # Прогоняем X_prod через каждую сохраненную модель
        for feat, model_file in MODEL_FILES.items():
            if os.path.exists(model_file):
                logger.info(f"Предсказание для {feat}...")
                model = FeatureRegressor.load(model_file)
                df.loc[work_mask, feat] = model.predict(X_prod)
            else:
                logger.warning(f"Модель {model_file} не найдена. Пропуск {feat}.")

    # Возвращаем эмбеддинги в JSON для сохранения
    df["embedding_json"] = df["embedding_json"].apply(format_embedding_for_csv)

    output_name = "features_scored_" + os.path.basename(csv_path)
    df.to_csv(output_name, sep=sep, index=False)
    logger.info(f"Инференс завершен. Результат сохранен в: {output_name}")


# ================= ПРИМЕР ЗАПУСКА =================
if __name__ == "__main__":
    TRAIN_FILE = "/kaggle/input/datasets/alonix/marked-data-signals/signals_202605221954_data_export_labeled-4.csv"  # Замени на свой файл
    PROD_FILE = "/kaggle/input/datasets/alonix/marked-data-signals/signals_202605221954_data_export_labeled-4.csv"  # Замени на свой файл

    # --- 1. Обучение (запустить один раз) ---
    # train_feature_model(TRAIN_FILE, 'scale_score')
    # train_feature_model(TRAIN_FILE, 'urgency_score')
    train_feature_model(TRAIN_FILE, 'rigidity_score')

    # --- 2. Инференс (для продакшена) ---
    # inference_all_features(PROD_FILE)
    pass