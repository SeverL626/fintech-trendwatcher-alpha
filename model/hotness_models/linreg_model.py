
import pandas as pd
import numpy as np
import joblib
import logging
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error, r2_score

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger(__name__)

class HotnessLinearModel:
    def __init__(self, target_sum=5.0):
        self.target_sum = target_sum
        self.scaler = MinMaxScaler()
        # КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Включаем intercept для правильной математики
        self.model = LinearRegression(positive=True, fit_intercept=True)
        self.weights = None
        self.features = ['scale_score', 'urgency_score', 'rigidity_score', 'dup_count_norm', 'auth_score']

    def _build_authority_dicts(self, df_raw, df_sources):
        raw_to_source = dict(zip(df_raw['id'].astype(str), df_raw['source_id'].astype(str)))
        source_to_auth = dict(zip(df_sources['id'].astype(str), df_sources['authority_score'].astype(float)))
        return raw_to_source, source_to_auth

    def _get_max_authority(self, sources_str, raw_to_source, source_to_auth):
        if pd.isna(sources_str) or not str(sources_str).strip():
            return 0.0

        raw_ids = [s.strip() for s in str(sources_str).split(',')]
        auths = [source_to_auth.get(raw_to_source.get(rid), 0.0) for rid in raw_ids]
        return max(auths) if auths else 0.0

    def prepare_data(self, df_signals, df_raw, df_sources, is_train=True):
        raw_to_source, source_to_auth = self._build_authority_dicts(df_raw, df_sources)

        if is_train:
            grouped = df_signals.groupby('duplicate_group_id')
            df_agg = grouped.agg({
                'scale_score': 'mean',
                'urgency_score': 'mean',
                'rigidity_score': 'mean',
                'hotness': 'mean',
                'id': 'count',
                'sources': lambda x: ','.join(x.dropna().astype(str))
            }).rename(columns={'id': 'raw_dup_count'})
        else:
            df_agg = df_signals[df_signals['is_duplicate'] == 0].copy()
            group_sizes = df_signals.groupby('duplicate_group_id').size()
            df_agg['raw_dup_count'] = df_agg['duplicate_group_id'].map(group_sizes)
            df_agg = df_agg.set_index('id')

        df_agg['dup_count_norm'] = np.log1p(df_agg['raw_dup_count'])
        df_agg['auth_score'] = df_agg['sources'].apply(
            lambda x: self._get_max_authority(x, raw_to_source, source_to_auth)
        )

        df_agg = df_agg.dropna(subset=self.features)
        return df_agg

    def fit(self, df_train, df_raw, df_sources):
        logger.info("Подготовка обучающей выборки...")
        df_agg = self.prepare_data(df_train, df_raw, df_sources, is_train=True)

        X = df_agg[self.features].values
        y = df_agg['hotness'].values

        X_scaled = self.scaler.fit_transform(X)

        logger.info("Шаг 1: Обучение ML-модели для проверки связей...")
        self.model.fit(X_scaled, y)

        # СЧИТАЕМ МЕТРИКИ НА ЧЕСТНЫХ ВЕСАХ
        preds = self.model.predict(X_scaled)

        logger.info("--- Статистические ML-метрики ---")
        logger.info(f"R^2 Score: {r2_score(y, preds):.4f}")
        logger.info(f"MSE: {mean_squared_error(y, preds):.4f}")
        logger.info(f"Сдвиг (Intercept): {self.model.intercept_:.4f}")

        raw_weights = self.model.coef_
        logger.info("\n--- Сырые веса модели (влияние признаков) ---")
        for f, w in zip(self.features, raw_weights):
            logger.info(f"{f:15}: {w:.4f}")

        # ШАГ 2: СОЗДАНИЕ ИНДЕКСА ДЛЯ БИЗНЕСА (СУММА = 5.0)
        if raw_weights.sum() > 0:
            self.weights = (raw_weights / raw_weights.sum()) * self.target_sum
        else:
            logger.warning("Модель занулила все веса. Проверьте таргет.")
            self.weights = np.ones(len(self.features)) * (self.target_sum / len(self.features))

        # Отключаем свободный член и применяем нормированные веса для инференса
        self.model.fit_intercept = False
        self.model.intercept_ = 0.0
        self.model.coef_ = self.weights

        logger.info("\n--- Финальная бизнес-формула для прода (Сумма = 5.0) ---")
        for f, w in zip(self.features, self.weights):
            logger.info(f"{f:15}: {w:.4f}")

    def predict_from_features(self, X_scaled):
        # Инференс теперь делает чистое скалярное произведение w * x
        return np.dot(X_scaled, self.weights)

    def predict(self, df_infer, df_raw, df_sources):
        df_agg = self.prepare_data(df_infer, df_raw, df_sources, is_train=False)
        if df_agg.empty: return df_agg

        X = df_agg[self.features].values
        X_scaled = self.scaler.transform(X)

        df_agg['predicted_hotness'] = self.predict_from_features(X_scaled)
        return df_agg

    def save(self, filepath="hotness_model.pkl"):
        joblib.dump({'scaler': self.scaler, 'weights': self.weights, 'features': self.features}, filepath)

    @classmethod
    def load(cls, filepath="hotness_model.pkl"):
        instance = cls()
        data = joblib.load(filepath)
        instance.scaler = data['scaler']
        instance.weights = data['weights']
        instance.features = data['features']
        instance.model.fit_intercept = False
        instance.model.intercept_ = 0.0
        instance.model.coef_ = instance.weights
        return instance