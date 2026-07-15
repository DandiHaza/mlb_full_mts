from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf, OAS
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler


class DualReferenceMTS:
    """Common-covariance dual-reference MTS.

    Fit scaler and covariance on healthy reference only.
    Estimate two centers: healthy center and TJS center.
    Score(x) = log((D_H + eps) / (D_T + eps)).
    """

    def __init__(self, covariance: str = "oas", eps: float = 1e-6):
        if covariance not in {"oas", "ledoit_wolf"}:
            raise ValueError("covariance must be 'oas' or 'ledoit_wolf'")
        self.covariance = covariance
        self.eps = eps
        self.scaler = StandardScaler()
        self.cov_estimator = None
        self.precision_ = None
        self.mu_h_ = None
        self.mu_t_ = None
        self.features_: list[str] | None = None

    def fit(self, X_healthy: pd.DataFrame, X_tjs: pd.DataFrame):
        self.features_ = list(X_healthy.columns)
        Xh = self.scaler.fit_transform(X_healthy)
        Xt = self.scaler.transform(X_tjs)
        self.mu_h_ = np.nanmean(Xh, axis=0)
        self.mu_t_ = np.nanmean(Xt, axis=0)
        if self.covariance == "oas":
            self.cov_estimator = OAS(store_precision=True, assume_centered=False)
        else:
            self.cov_estimator = LedoitWolf(store_precision=True, assume_centered=False)
        self.cov_estimator.fit(Xh)
        self.precision_ = self.cov_estimator.precision_
        return self

    def _mahalanobis(self, X_scaled: np.ndarray, center: np.ndarray) -> np.ndarray:
        diff = X_scaled - center
        dist_sq = np.einsum("ij,jk,ik->i", diff, self.precision_, diff)
        return np.sqrt(np.maximum(dist_sq, 0.0))

    def score(self, X: pd.DataFrame) -> pd.DataFrame:
        if self.features_ is None:
            raise RuntimeError("Model is not fitted.")
        Xs = self.scaler.transform(X[self.features_])
        d_h = self._mahalanobis(Xs, self.mu_h_)
        d_t = self._mahalanobis(Xs, self.mu_t_)
        risk = np.log((d_h + self.eps) / (d_t + self.eps))
        return pd.DataFrame({"D_H": d_h, "D_T": d_t, "risk_tjs": risk}, index=X.index)


def coerce_feature_matrix(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    X = df[features].copy()
    for col in features:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    return X.replace([np.inf, -np.inf], np.nan)


def fit_feature_medians(df: pd.DataFrame, features: list[str]) -> pd.Series:
    X = coerce_feature_matrix(df, features)
    return X.median(numeric_only=True).reindex(features)


def prepare_feature_matrix(
    df: pd.DataFrame,
    features: list[str],
    impute_values: pd.Series | dict[str, float] | None = None,
) -> pd.DataFrame:
    X = coerce_feature_matrix(df, features)
    medians = pd.Series(impute_values).reindex(features) if impute_values is not None else X.median(numeric_only=True).reindex(features)
    return X.fillna(medians)


def row_level_metrics(y_true: Iterable[int], risk: Iterable[float]) -> dict:
    y = np.asarray(list(y_true), dtype=int)
    s = np.asarray(list(risk), dtype=float)
    out = {}
    if len(np.unique(y)) > 1:
        out["roc_auc"] = float(roc_auc_score(y, s))
        out["pr_auc"] = float(average_precision_score(y, s))
    else:
        out["roc_auc"] = None
        out["pr_auc"] = None
    return out


def summarize_alerts(scored: pd.DataFrame, threshold: float) -> dict:
    out = {}
    scored = scored.copy()
    scored["alert"] = scored["risk_tjs"] >= threshold
    out["threshold"] = float(threshold)
    out["n_windows"] = int(len(scored))
    out["n_alerts"] = int(scored["alert"].sum())
    if "sample_group" in scored.columns:
        out["alerts_by_group"] = scored.groupby("sample_group")["alert"].sum().astype(int).to_dict()
        out["windows_by_group"] = scored.groupby("sample_group")["alert"].size().astype(int).to_dict()
    if {"pitcher", "season"}.issubset(scored.columns):
        n_ps = scored[["pitcher", "season"]].drop_duplicates().shape[0]
        false_alerts = scored[(scored["alert"]) & (scored.get("sample_group") != "tjs")].shape[0]
        out["false_alerts_per_pitcher_season"] = float(false_alerts / n_ps) if n_ps else None
    return out


def save_json(obj: dict, path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
