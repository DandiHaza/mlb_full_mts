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


def add_role_proxy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pitch_mean = pd.to_numeric(df.get("pitch_count_mean_10"), errors="coerce")
    df["role_proxy"] = "swing_mixed"
    df.loc[pitch_mean <= 35, "role_proxy"] = "relief_like"
    df.loc[pitch_mean >= 60, "role_proxy"] = "starter_like"
    df.loc[pitch_mean.isna(), "role_proxy"] = "unknown"
    return df


def resolve_features(df: pd.DataFrame, cfg: dict) -> tuple[list[str], list[str]]:
    feature_set_name = cfg["mts"]["feature_set"]
    configured = cfg["features"][feature_set_name]
    present = [f for f in configured if f in df.columns]
    missing = [f for f in configured if f not in df.columns]
    all_missing = [f for f in present if df[f].replace([np.inf, -np.inf], np.nan).isna().all()]
    return [f for f in present if f not in all_missing], missing + all_missing


def fit_role_specific_mts(model_df: pd.DataFrame, features: list[str], cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored_parts = []
    summary_rows = []
    min_healthy_buffer = int(cfg.get("diagnostics", {}).get("min_healthy_buffer", 5))
    min_tjs_windows = int(cfg.get("diagnostics", {}).get("min_tjs_windows", 5))
    threshold_percentile = float(cfg["mts"].get("threshold_percentile", 95))

    for role, g in model_df.groupby("role_proxy", dropna=False):
        g = g.copy()
        n_healthy = int(g["sample_group"].eq("healthy").sum())
        n_tjs = int(g["sample_group"].eq("tjs").sum())
        role_features = [f for f in features if not g.loc[g["sample_group"] == "healthy", f].replace([np.inf, -np.inf], np.nan).isna().all()]
        usable = n_healthy >= len(role_features) + min_healthy_buffer and n_tjs >= min_tjs_windows and len(role_features) >= 5

        row = {
            "role_proxy": role,
            "n_windows": int(len(g)),
            "n_healthy_windows": n_healthy,
            "n_tjs_windows": n_tjs,
            "n_features": len(role_features),
            "status": "fit" if usable else "skipped",
        }
        if not usable:
            row.update({
                "roc_auc": None,
                "pr_auc": None,
                "threshold": None,
                "healthy_alert_windows": None,
                "tjs_alert_windows": None,
            })
            summary_rows.append(row)
            continue

        medians = fit_feature_medians(g[g["sample_group"] == "healthy"], role_features)
        X = prepare_feature_matrix(g, role_features, impute_values=medians)
        X_h = X[g["sample_group"] == "healthy"]
        X_t = X[g["sample_group"] == "tjs"]

        mts = DualReferenceMTS(covariance=cfg["mts"].get("covariance", "oas"), eps=float(cfg["mts"].get("eps", 1e-6)))
        mts.fit(X_h, X_t)
        scores = mts.score(X).rename(columns={
            "D_H": "D_H_role",
            "D_T": "D_T_role",
            "risk_tjs": "risk_tjs_role",
        })

        scored = pd.concat([g.reset_index(drop=True), scores.reset_index(drop=True)], axis=1)
        scored["y_true"] = (scored["sample_group"] == "tjs").astype(int)
        threshold = np.nanpercentile(scored.loc[scored["sample_group"] == "healthy", "risk_tjs_role"], threshold_percentile)
        scored["alert_role"] = scored["risk_tjs_role"] >= threshold
        metrics = row_level_metrics(scored["y_true"], scored["risk_tjs_role"])
        alert_summary = summarize_alerts(
            scored.rename(columns={"risk_tjs_role": "risk_tjs", "alert_role": "alert"}),
            threshold,
        )

        row.update({
            **metrics,
            "threshold": float(threshold),
            "healthy_alert_windows": int(scored.loc[scored["sample_group"] == "healthy", "alert_role"].sum()),
            "tjs_alert_windows": int(scored.loc[scored["sample_group"] == "tjs", "alert_role"].sum()),
            "healthy_alert_rate": float(scored.loc[scored["sample_group"] == "healthy", "alert_role"].mean()),
            "tjs_alert_rate": float(scored.loc[scored["sample_group"] == "tjs", "alert_role"].mean()),
            "false_alerts_per_pitcher_season": alert_summary.get("false_alerts_per_pitcher_season"),
        })
        summary_rows.append(row)
        scored_parts.append(scored)

    scored_all = pd.concat(scored_parts, ignore_index=True) if scored_parts else pd.DataFrame()
    summary = pd.DataFrame(summary_rows).sort_values("role_proxy").reset_index(drop=True)
    return scored_all, summary


def season_balanced_sampling(
    scored: pd.DataFrame,
    *,
    random_seed: int,
    n_iter: int,
    healthy_per_tjs: int,
) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(random_seed)
    scored = scored[scored["sample_group"].isin(["healthy", "tjs"])].copy()
    scored["season"] = pd.to_numeric(scored["season"], errors="coerce").astype("Int64")
    eligible_seasons = []
    for season, g in scored.groupby("season", dropna=True):
        n_h = int(g["sample_group"].eq("healthy").sum())
        n_t = int(g["sample_group"].eq("tjs").sum())
        if n_h > 0 and n_t > 0:
            eligible_seasons.append(int(season))

    rows = []
    for i in range(n_iter):
        sampled_parts = []
        for season in eligible_seasons:
            g = scored[scored["season"] == season]
            tjs = g[g["sample_group"] == "tjs"]
            healthy = g[g["sample_group"] == "healthy"]
            target_healthy = min(len(healthy), max(1, healthy_per_tjs * len(tjs)))
            sampled_idx = rng.choice(healthy.index.to_numpy(), size=target_healthy, replace=False)
            sampled_parts.append(pd.concat([tjs, healthy.loc[sampled_idx]], ignore_index=False))
        sample = pd.concat(sampled_parts, ignore_index=False) if sampled_parts else pd.DataFrame()
        if sample.empty:
            continue
        y_true = (sample["sample_group"] == "tjs").astype(int)
        metrics = row_level_metrics(y_true, sample["risk_tjs"])
        rows.append({
            "iteration": i,
            "n_windows": int(len(sample)),
            "healthy_windows": int(sample["sample_group"].eq("healthy").sum()),
            "tjs_windows": int(sample["sample_group"].eq("tjs").sum()),
            "eligible_seasons": ",".join(map(str, eligible_seasons)),
            **metrics,
        })

    iter_df = pd.DataFrame(rows)
    aggregate = {
        "random_seed": random_seed,
        "n_iter": n_iter,
        "healthy_per_tjs": healthy_per_tjs,
        "eligible_seasons": eligible_seasons,
        "mean_roc_auc": float(iter_df["roc_auc"].mean()) if not iter_df.empty else None,
        "std_roc_auc": float(iter_df["roc_auc"].std()) if len(iter_df) > 1 else None,
        "mean_pr_auc": float(iter_df["pr_auc"].mean()) if not iter_df.empty else None,
        "std_pr_auc": float(iter_df["pr_auc"].std()) if len(iter_df) > 1 else None,
        "mean_healthy_windows": float(iter_df["healthy_windows"].mean()) if not iter_df.empty else None,
        "mean_tjs_windows": float(iter_df["tjs_windows"].mean()) if not iter_df.empty else None,
    }
    return iter_df, aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare pooled MTS with role-specific and season-balanced diagnostics.")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--balanced-iters", type=int, default=100)
    parser.add_argument("--healthy-per-tjs", type=int, default=5)
    args = parser.parse_args()
    cfg = load_config(args.config)

    processed = Path(cfg["paths"]["processed_dir"])
    reports = Path(cfg["paths"]["reports_dir"])
    reports.mkdir(parents=True, exist_ok=True)

    windows = pd.read_csv(processed / "window_features.csv", low_memory=False)
    windows = add_role_proxy(windows)
    model_df = windows[windows["sample_group"].isin(["healthy", "tjs"])].copy()
    features, missing = resolve_features(model_df, cfg)
    if len(features) < 5:
        raise ValueError(f"Too few features available for diagnostics: {features}")

    role_scores, role_summary = fit_role_specific_mts(model_df, features, cfg)
    role_scores.to_csv(reports / "role_specific_mts_scores.csv", index=False)
    role_summary.to_csv(reports / "role_specific_mts_summary.csv", index=False)

    pooled_scores = pd.read_csv(processed / "mts_scores.csv", low_memory=False)
    balanced_iter, balanced_summary = season_balanced_sampling(
        pooled_scores,
        random_seed=int(cfg["project"].get("random_seed", 42)),
        n_iter=args.balanced_iters,
        healthy_per_tjs=args.healthy_per_tjs,
    )
    balanced_iter.to_csv(reports / "season_balanced_sampling_iterations.csv", index=False)
    save_json({
        "feature_set": cfg["mts"]["feature_set"],
        "features_used": features,
        "features_missing": missing,
        "role_specific_mts": role_summary.to_dict(orient="records"),
        "season_balanced_sampling": balanced_summary,
        "notes": [
            "Role-specific MTS fits separate healthy scaler/covariance and TJS center within each role_proxy.",
            "Season-balanced sampling reuses pooled MTS risk_tjs and downsamples healthy windows within seasons that contain both healthy and TJS windows.",
        ],
    }, reports / "mts_variant_diagnostics.json")

    print(f"Saved role-specific MTS scores -> {reports / 'role_specific_mts_scores.csv'}")
    print(f"Saved role-specific MTS summary -> {reports / 'role_specific_mts_summary.csv'}")
    print(f"Saved season-balanced iterations -> {reports / 'season_balanced_sampling_iterations.csv'}")
    print(f"Saved variant diagnostics -> {reports / 'mts_variant_diagnostics.json'}")
    print("Role-specific MTS summary:")
    print(role_summary.to_string(index=False))
    print("Season-balanced pooled-score diagnostic:")
    print(balanced_summary)


if __name__ == "__main__":
    main()
