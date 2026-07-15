from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mts_utils import DualReferenceMTS, fit_feature_medians, prepare_feature_matrix, row_level_metrics, summarize_alerts


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_json(obj: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def resolve_features(df: pd.DataFrame, cfg: dict) -> tuple[list[str], list[str]]:
    feature_set_name = cfg["mts"]["feature_set"]
    configured = cfg["features"][feature_set_name]
    present = [f for f in configured if f in df.columns]
    missing = [f for f in configured if f not in df.columns]
    all_missing = [f for f in present if df[f].replace([np.inf, -np.inf], np.nan).isna().all()]
    return [f for f in present if f not in all_missing], missing + all_missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and score a holdout-season test set.")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--test-season", type=int, default=2018)
    args = parser.parse_args()
    cfg = load_config(args.config)

    processed = Path(cfg["paths"]["processed_dir"])
    reports = Path(cfg["paths"]["reports_dir"])
    processed.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    windows = pd.read_csv(processed / "window_features.csv", low_memory=False)
    windows["season"] = pd.to_numeric(windows["season"], errors="coerce").astype("Int64")
    model_df = windows[windows["sample_group"].isin(["healthy", "tjs"])].copy()
    features, missing = resolve_features(model_df, cfg)

    train_df = model_df[model_df["season"] != args.test_season].copy()
    test_df = model_df[model_df["season"] == args.test_season].copy()
    if test_df.empty:
        raise ValueError(f"No test windows found for season {args.test_season}.")
    if train_df["sample_group"].eq("healthy").sum() == 0:
        raise ValueError("No healthy train windows available.")
    if train_df["sample_group"].eq("tjs").sum() == 0:
        raise ValueError("No TJS train windows available.")

    healthy_all_missing = [
        f for f in features
        if train_df.loc[train_df["sample_group"] == "healthy", f].replace([np.inf, -np.inf], np.nan).isna().all()
    ]
    features = [f for f in features if f not in healthy_all_missing]
    if len(features) < 5:
        raise ValueError(f"Too few usable features for holdout test: {features}")

    medians = fit_feature_medians(train_df[train_df["sample_group"] == "healthy"], features)
    X_train = prepare_feature_matrix(train_df, features, impute_values=medians)
    X_test = prepare_feature_matrix(test_df, features, impute_values=medians)

    mts = DualReferenceMTS(
        covariance=cfg["mts"].get("covariance", "oas"),
        eps=float(cfg["mts"].get("eps", 1e-6)),
    )
    mts.fit(
        X_train[train_df["sample_group"] == "healthy"],
        X_train[train_df["sample_group"] == "tjs"],
    )
    train_scores = mts.score(X_train)
    test_scores = mts.score(X_test)

    scored_train = pd.concat([train_df.reset_index(drop=True), train_scores.reset_index(drop=True)], axis=1)
    scored_test = pd.concat([test_df.reset_index(drop=True), test_scores.reset_index(drop=True)], axis=1)
    threshold = np.nanpercentile(
        scored_train.loc[scored_train["sample_group"] == "healthy", "risk_tjs"],
        cfg["mts"].get("threshold_percentile", 95),
    )
    scored_train["alert"] = scored_train["risk_tjs"] >= threshold
    scored_test["alert"] = scored_test["risk_tjs"] >= threshold
    scored_train["y_true"] = (scored_train["sample_group"] == "tjs").astype(int)
    scored_test["y_true"] = (scored_test["sample_group"] == "tjs").astype(int)

    test_windows_path = processed / f"holdout_{args.test_season}_test_windows.csv"
    test_scores_path = processed / f"holdout_{args.test_season}_mts_scores.csv"
    summary_path = reports / f"holdout_{args.test_season}_summary.json"

    test_df.to_csv(test_windows_path, index=False)
    scored_test.to_csv(test_scores_path, index=False)

    summary = {
        "test_season": args.test_season,
        "feature_set": cfg["mts"]["feature_set"],
        "features_used": features,
        "features_missing": missing + healthy_all_missing,
        "threshold_source": "train_healthy_percentile",
        "threshold_percentile": cfg["mts"].get("threshold_percentile", 95),
        "threshold": float(threshold),
        "train": {
            "n_windows": int(len(scored_train)),
            "n_healthy_windows": int(scored_train["sample_group"].eq("healthy").sum()),
            "n_tjs_windows": int(scored_train["sample_group"].eq("tjs").sum()),
            "row_level_metrics": row_level_metrics(scored_train["y_true"], scored_train["risk_tjs"]),
            "alerts": summarize_alerts(scored_train, threshold),
        },
        "test": {
            "n_windows": int(len(scored_test)),
            "n_healthy_windows": int(scored_test["sample_group"].eq("healthy").sum()),
            "n_tjs_windows": int(scored_test["sample_group"].eq("tjs").sum()),
            "row_level_metrics": row_level_metrics(scored_test["y_true"], scored_test["risk_tjs"]),
            "alerts": summarize_alerts(scored_test, threshold),
        },
        "note": (
            "This is a holdout-season test set. It tests cross-season separation, "
            "not a strict chronological prospective deployment."
        ),
    }
    save_json(summary, summary_path)

    print(f"Saved holdout test windows -> {test_windows_path}")
    print(f"Saved holdout MTS scores -> {test_scores_path}")
    print(f"Saved holdout summary -> {summary_path}")
    print("Holdout diagnostics:")
    print(f"  train healthy: {summary['train']['n_healthy_windows']}")
    print(f"  train TJS: {summary['train']['n_tjs_windows']}")
    print(f"  test healthy: {summary['test']['n_healthy_windows']}")
    print(f"  test TJS: {summary['test']['n_tjs_windows']}")
    print(f"  test metrics: {summary['test']['row_level_metrics']}")
    print(f"  test alerts: {summary['test']['alerts']}")


if __name__ == "__main__":
    main()
