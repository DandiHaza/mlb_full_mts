from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml
from sklearn.metrics import average_precision_score, roc_auc_score


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_json(obj: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def add_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["window_end_date"] = pd.to_datetime(df["window_end_date"], errors="coerce")
    df["season"] = df["window_end_date"].dt.year
    df["month"] = df["window_end_date"].dt.to_period("M").astype(str)
    return df


def add_role_proxy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pitch_mean = pd.to_numeric(df.get("pitch_count_mean_10"), errors="coerce")
    df["role_proxy"] = "swing_mixed"
    df.loc[pitch_mean <= 35, "role_proxy"] = "relief_like"
    df.loc[pitch_mean >= 60, "role_proxy"] = "starter_like"
    df.loc[pitch_mean.isna(), "role_proxy"] = "unknown"
    return df


def binary_metrics(group: pd.DataFrame) -> dict:
    if group["sample_group"].nunique() < 2:
        return {"roc_auc": None, "pr_auc": None}
    y_true = (group["sample_group"] == "tjs").astype(int)
    risk = pd.to_numeric(group["risk_tjs"], errors="coerce")
    valid = risk.notna()
    if valid.sum() == 0 or y_true[valid].nunique() < 2:
        return {"roc_auc": None, "pr_auc": None}
    return {
        "roc_auc": float(roc_auc_score(y_true[valid], risk[valid])),
        "pr_auc": float(average_precision_score(y_true[valid], risk[valid])),
    }


def summarize_groups(scored: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, g in scored.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        healthy = g[g["sample_group"] == "healthy"]
        tjs = g[g["sample_group"] == "tjs"]
        metrics = binary_metrics(g)
        row = {col: value for col, value in zip(group_cols, keys)}
        row.update({
            "n_windows": int(len(g)),
            "healthy_windows": int(len(healthy)),
            "tjs_windows": int(len(tjs)),
            "healthy_alert_windows": int(healthy["alert"].sum()),
            "tjs_alert_windows": int(tjs["alert"].sum()),
            "healthy_alert_rate": float(healthy["alert"].mean()) if len(healthy) else None,
            "tjs_alert_rate": float(tjs["alert"].mean()) if len(tjs) else None,
            "healthy_mean_risk": float(healthy["risk_tjs"].mean()) if len(healthy) else None,
            "tjs_mean_risk": float(tjs["risk_tjs"].mean()) if len(tjs) else None,
            "healthy_max_risk": float(healthy["risk_tjs"].max()) if len(healthy) else None,
            "tjs_max_risk": float(tjs["risk_tjs"].max()) if len(tjs) else None,
            **metrics,
        })
        rows.append(row)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def summarize_healthy_alerts(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    healthy = scored[scored["sample_group"] == "healthy"].copy()
    alerts = healthy[healthy["alert"]].copy()

    pitcher_summary = (
        healthy.groupby(["pitcher", "mlbamid", "player_name"], dropna=False)
        .agg(
            healthy_windows=("alert", "size"),
            alert_windows=("alert", "sum"),
            max_risk_tjs=("risk_tjs", "max"),
            mean_risk_tjs=("risk_tjs", "mean"),
            first_window_end=("window_end_date", "min"),
            last_window_end=("window_end_date", "max"),
        )
        .reset_index()
    )
    pitcher_summary["alert_rate"] = pitcher_summary["alert_windows"] / pitcher_summary["healthy_windows"]
    pitcher_summary = pitcher_summary.sort_values(
        ["alert_windows", "max_risk_tjs", "alert_rate"],
        ascending=[False, False, False],
    )

    month_summary = (
        healthy.groupby("month", dropna=False)
        .agg(
            healthy_windows=("alert", "size"),
            alert_windows=("alert", "sum"),
            unique_pitchers=("pitcher", "nunique"),
            max_risk_tjs=("risk_tjs", "max"),
            mean_risk_tjs=("risk_tjs", "mean"),
        )
        .reset_index()
        .sort_values("month")
    )
    month_summary["alert_rate"] = month_summary["alert_windows"] / month_summary["healthy_windows"]

    top_alert_windows = alerts.sort_values("risk_tjs", ascending=False)
    return pitcher_summary, month_summary, top_alert_windows


def summarize_tjs_capture(scored: pd.DataFrame) -> pd.DataFrame:
    tjs = scored[scored["sample_group"] == "tjs"].copy()
    if tjs.empty:
        return pd.DataFrame()
    tjs["risk_rank_desc"] = tjs["risk_tjs"].rank(method="first", ascending=False).astype(int)
    cols = [c for c in [
        "event_id", "player_name", "mlbamid", "pitcher", "season", "window_end_date",
        "surgery_date", "days_to_surgery", "D_H", "D_T", "risk_tjs", "alert", "risk_rank_desc",
    ] if c in tjs.columns]
    return tjs.sort_values("risk_tjs", ascending=False)[cols]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize healthy false-positive alerts and TJS anchor capture.")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)

    processed = Path(cfg["paths"]["processed_dir"])
    reports = Path(cfg["paths"]["reports_dir"])
    reports.mkdir(parents=True, exist_ok=True)

    scored = pd.read_csv(processed / "mts_scores.csv", low_memory=False)
    if "alert" not in scored.columns:
        raise KeyError("mts_scores.csv is missing alert column. Run src/05_run_mts.py first.")
    scored["alert"] = scored["alert"].astype(str).str.lower().isin(["true", "1", "yes"])
    scored = add_time_columns(scored)
    scored = add_role_proxy(scored)

    pitcher_summary, month_summary, top_alert_windows = summarize_healthy_alerts(scored)
    tjs_ranked = summarize_tjs_capture(scored)
    role_summary = summarize_groups(scored, ["role_proxy"])
    season_summary = summarize_groups(scored, ["season"])
    season_role_summary = summarize_groups(scored, ["season", "role_proxy"])

    pitcher_path = reports / "healthy_alert_pitcher_summary.csv"
    month_path = reports / "healthy_alert_month_summary.csv"
    top_path = reports / "healthy_alert_top_windows.csv"
    tjs_path = reports / "tjs_anchor_capture_summary.csv"
    role_path = reports / "role_proxy_summary.csv"
    season_path = reports / "season_group_summary.csv"
    season_role_path = reports / "season_role_summary.csv"

    pitcher_summary.to_csv(pitcher_path, index=False)
    month_summary.to_csv(month_path, index=False)
    top_alert_windows.to_csv(top_path, index=False)
    tjs_ranked.to_csv(tjs_path, index=False)
    role_summary.to_csv(role_path, index=False)
    season_summary.to_csv(season_path, index=False)
    season_role_summary.to_csv(season_role_path, index=False)

    healthy = scored[scored["sample_group"] == "healthy"]
    tjs = scored[scored["sample_group"] == "tjs"]
    diagnostics = {
        "n_scored_windows": int(len(scored)),
        "n_healthy_windows": int(len(healthy)),
        "n_tjs_windows": int(len(tjs)),
        "n_healthy_alert_windows": int(healthy["alert"].sum()),
        "n_tjs_alert_windows": int(tjs["alert"].sum()),
        "healthy_alert_rate": float(healthy["alert"].mean()) if len(healthy) else None,
        "tjs_alert_rate": float(tjs["alert"].mean()) if len(tjs) else None,
        "n_healthy_pitchers": int(healthy["pitcher"].nunique()) if "pitcher" in healthy.columns else None,
        "n_healthy_pitchers_with_alert": int(healthy.loc[healthy["alert"], "pitcher"].nunique()) if "pitcher" in healthy.columns else None,
        "role_proxy_rule": "starter_like if pitch_count_mean_10 >= 60; relief_like if <= 35; otherwise swing_mixed",
        "top_healthy_alert_pitchers": pitcher_summary.head(20).to_dict(orient="records"),
        "monthly_alert_summary": month_summary.to_dict(orient="records"),
        "role_proxy_summary": role_summary.to_dict(orient="records"),
        "season_group_summary": season_summary.to_dict(orient="records"),
    }
    save_json(diagnostics, reports / "alert_diagnostics.json")

    print(f"Saved healthy alert pitcher summary -> {pitcher_path}")
    print(f"Saved healthy alert month summary -> {month_path}")
    print(f"Saved top healthy alert windows -> {top_path}")
    print(f"Saved TJS anchor capture summary -> {tjs_path}")
    print(f"Saved role proxy summary -> {role_path}")
    print(f"Saved season group summary -> {season_path}")
    print(f"Saved season-role summary -> {season_role_path}")
    print(f"Saved alert diagnostics -> {reports / 'alert_diagnostics.json'}")
    print("Alert diagnostics:")
    print(f"  healthy alert windows: {diagnostics['n_healthy_alert_windows']} / {diagnostics['n_healthy_windows']}")
    print(f"  TJS alert windows: {diagnostics['n_tjs_alert_windows']} / {diagnostics['n_tjs_windows']}")
    print(f"  healthy pitchers with alert: {diagnostics['n_healthy_pitchers_with_alert']} / {diagnostics['n_healthy_pitchers']}")


if __name__ == "__main__":
    main()
