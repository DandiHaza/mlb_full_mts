from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml

from mts_utils import DualReferenceMTS, fit_feature_medians, prepare_feature_matrix, row_level_metrics, save_json, summarize_alerts


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")


def main():
    configure_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)

    processed = Path(cfg["paths"]["processed_dir"])
    reports = Path(cfg["paths"]["reports_dir"])
    reports.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(processed / "window_features.csv", parse_dates=["window_start_date", "window_end_date", "surgery_date"])

    feature_set_name = cfg["mts"]["feature_set"]
    features = cfg["features"][feature_set_name]
    # Keep only features that are actually present; report missing.
    present = [f for f in features if f in df.columns]
    missing = [f for f in features if f not in df.columns]
    if missing:
        print("Missing features skipped:", missing)
    model_df = df[df["sample_group"].isin(["healthy", "tjs"])].copy()
    all_missing = [f for f in present if model_df[f].replace([np.inf, -np.inf], np.nan).isna().all()]
    if all_missing:
        print("All-empty features skipped:", all_missing)
    features = [f for f in present if f not in all_missing]
    healthy_df = model_df[model_df["sample_group"] == "healthy"]
    healthy_all_missing = [f for f in features if healthy_df[f].replace([np.inf, -np.inf], np.nan).isna().all()]
    if healthy_all_missing:
        print("Healthy-reference all-empty features skipped:", healthy_all_missing)
    features = [f for f in features if f not in healthy_all_missing]
    if len(features) < 5:
        raise ValueError(f"Too few features available: {features}")

    n_healthy = int(model_df["sample_group"].eq("healthy").sum())
    n_tjs = int(model_df["sample_group"].eq("tjs").sum())
    if n_healthy == 0:
        raise ValueError(
            "No healthy windows are available. Add league-wide Statcast chunks with "
            "src/02b_collect_statcast_league_chunks.py or include non-nearby TJS pitcher windows."
        )
    if n_tjs == 0:
        raise ValueError(
            "No TJS anchor windows are available. Collect enough pre-surgery Statcast data, "
            "then rerun 03_build_pitcher_game_log.py and 04_build_windows.py."
        )
    if n_tjs < 2:
        print("Warning: fewer than 2 TJS windows. MTS can run, but reference center will be unstable.")
    if n_healthy < len(features) + 5:
        print("Warning: healthy reference is small relative to feature count. Use league-wide controls if possible.")

    healthy_medians = fit_feature_medians(model_df[model_df["sample_group"] == "healthy"], features)
    X_all = prepare_feature_matrix(model_df, features, impute_values=healthy_medians)
    X_h = X_all[model_df["sample_group"] == "healthy"]
    X_t = X_all[model_df["sample_group"] == "tjs"]

    mts = DualReferenceMTS(covariance=cfg["mts"].get("covariance", "oas"), eps=float(cfg["mts"].get("eps", 1e-6)))
    mts.fit(X_h, X_t)
    scores = mts.score(X_all)
    scored = pd.concat([model_df.reset_index(drop=True), scores.reset_index(drop=True)], axis=1)
    scored["y_true"] = (scored["sample_group"] == "tjs").astype(int)

    threshold = np.nanpercentile(scored.loc[scored["sample_group"] == "healthy", "risk_tjs"], cfg["mts"].get("threshold_percentile", 95))
    scored["alert"] = scored["risk_tjs"] >= threshold
    summary = {
        "feature_set": feature_set_name,
        "features_used": features,
        "features_missing": missing + all_missing + healthy_all_missing,
        "imputation_reference": "healthy_median",
        "n_healthy_windows": n_healthy,
        "n_tjs_windows": n_tjs,
        "row_level_metrics": row_level_metrics(scored["y_true"], scored["risk_tjs"]),
        "alerts": summarize_alerts(scored, threshold),
    }

    out_path = processed / "mts_scores.csv"
    scored.to_csv(out_path, index=False)
    review_cols = [c for c in [
        "player_name", "mlbamid", "pitcher", "season", "window_start_date", "window_end_date",
        "window_end_game_pk", "sample_group", "D_H", "D_T", "risk_tjs", "alert",
    ] if c in scored.columns]
    healthy_alerts = scored[(scored["sample_group"] == "healthy") & scored["alert"]].sort_values("risk_tjs", ascending=False)
    tjs_ranked = scored[scored["sample_group"] == "tjs"].sort_values("risk_tjs", ascending=False)
    healthy_alerts[review_cols].to_csv(reports / "healthy_alert_windows.csv", index=False)
    tjs_ranked[review_cols].to_csv(reports / "tjs_anchor_ranked_windows.csv", index=False)
    save_json(summary, reports / "mts_summary.json")
    print(f"Saved MTS scores -> {out_path}")
    print(f"Saved summary -> {reports / 'mts_summary.json'}")
    print(f"Saved healthy alert review file -> {reports / 'healthy_alert_windows.csv'}")
    print(f"Saved TJS anchor ranking file -> {reports / 'tjs_anchor_ranked_windows.csv'}")
    print("MTS diagnostics:")
    print(f"  healthy windows: {n_healthy}")
    print(f"  TJS windows: {n_tjs}")
    print(f"  feature columns used: {features}")
    print(f"  missing/skipped feature columns: {missing + all_missing + healthy_all_missing}")
    top_cols = [c for c in ["player_name", "mlbamid", "pitcher", "window_end_date", "sample_group", "D_H", "D_T", "risk_tjs"] if c in scored.columns]
    print("Top 20 highest-risk windows:")
    print(scored.sort_values("risk_tjs", ascending=False).head(20)[top_cols].to_string(index=False))


if __name__ == "__main__":
    main()
