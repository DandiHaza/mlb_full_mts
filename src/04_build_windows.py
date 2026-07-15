from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from feature_utils import linear_slope, safe_divide


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def weighted_mean(values, weights):
    v = pd.to_numeric(pd.Series(values), errors="coerce")
    w = pd.to_numeric(pd.Series(weights), errors="coerce")
    mask = v.notna() & w.notna() & (w > 0)
    if not mask.any():
        return np.nan
    return float(np.average(v[mask], weights=w[mask]))


def build_one_window(g: pd.DataFrame, idx: int, w: int) -> dict:
    win = g.iloc[idx - w + 1: idx + 1].copy()
    end = win.iloc[-1]
    suffix = f"_{w}"
    row = {
        "pitcher": int(end["pitcher"]),
        "mlbamid": int(end["pitcher"]),
        "player_name": end.get("player_name"),
        "window_start_date": win["game_date"].iloc[0],
        "window_end_date": win["game_date"].iloc[-1],
        "window_end_game_pk": end["game_pk"],
        "season": int(pd.Timestamp(end["game_date"]).year),
        "window_size": w,
        "w": w,
        "n_games": len(win),
        f"pitch_count_sum{suffix}": win["pitch_count"].sum(),
        f"pitch_count_mean{suffix}": win["pitch_count"].mean(),
        f"pitch_count_max{suffix}": win["pitch_count"].max(),
        f"tbf_sum{suffix}": win["tbf"].sum(),
        f"tbf_mean{suffix}": win["tbf"].mean(),
        f"rest_mean{suffix}": win["rest_days"].dropna().mean(),
        f"rest_min{suffix}": win["rest_days"].dropna().min(),
    }
    if "event_id_source_file" in win.columns:
        row["event_id_source_file"] = end.get("event_id_source_file")
    if "surgery_date_source_file" in win.columns:
        row["surgery_date_source_file"] = end.get("surgery_date_source_file")

    # Weighted rates and metrics.
    for col in ["k_rate", "bb_rate", "hr_rate"]:
        if col in win.columns:
            row[f"{col}{suffix}"] = weighted_mean(win[col], win["tbf"])
    for col in ["zone_rate", "whiff_rate", "called_strike_rate"]:
        if col in win.columns:
            row[f"{col}{suffix}"] = weighted_mean(win[col], win["pitch_count"])

    # Means, standard deviations, and slopes for continuous Statcast mechanics.
    continuous_cols = [
        "release_speed_mean", "fb_release_speed_mean", "release_spin_rate_mean",
        "fb_release_spin_rate_mean", "release_extension_mean", "release_pos_x_mean",
        "release_pos_z_mean", "release_pos_x_std", "release_pos_z_std",
        "release_pos_x_sd", "release_pos_z_sd", "pfx_x_mean", "pfx_z_mean",
    ]
    for col in continuous_cols:
        if col in win.columns:
            out_col = f"{col}{suffix}"
            row[out_col] = win[col].mean()
            if col.endswith("_mean"):
                row[f"{col.removesuffix('_mean')}_slope{suffix}"] = linear_slope(win[col]) if len(win) >= 2 else np.nan

    # Pitch mix shares.
    for col in [c for c in win.columns if c.endswith("_share")]:
        row[f"{col}{suffix}"] = weighted_mean(win[col], win["pitch_count"])

    # Slope of workload and rates.
    row[f"pitch_count_slope{suffix}"] = linear_slope(win["pitch_count"])
    if "tbf" in win.columns:
        row[f"tbf_slope{suffix}"] = linear_slope(win["tbf"])
    for col in ["bb_rate", "k_rate", "whiff_rate"]:
        if col in win.columns:
            row[f"{col}_slope{suffix}"] = linear_slope(win[col])
    return row


def build_windows(game_log: pd.DataFrame, w: int) -> pd.DataFrame:
    rows = []
    game_log = game_log.copy()
    game_log["game_date"] = pd.to_datetime(game_log["game_date"])
    for pitcher, g in game_log.groupby("pitcher", sort=False):
        g = g.sort_values(["game_date", "game_pk"]).reset_index(drop=True)
        if len(g) < w:
            continue
        for idx in range(w - 1, len(g)):
            rows.append(build_one_window(g, idx, w))
    return pd.DataFrame(rows)


def attach_tjs_labels(windows: pd.DataFrame, registry: pd.DataFrame, exclusion_before: int, exclusion_after: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    windows = windows.copy()
    registry = registry.copy()
    windows["sample_group"] = "healthy"
    windows["is_tjs_anchor"] = 0
    windows["event_id"] = pd.NA
    windows["surgery_date"] = pd.NaT
    windows["days_to_surgery"] = np.nan
    registry["last_appearance_date"] = pd.NaT
    registry["last_appearance_game_pk"] = pd.NA
    registry["valid_window"] = False

    windows["window_end_date"] = pd.to_datetime(windows["window_end_date"])
    registry["surgery_date"] = pd.to_datetime(registry["surgery_date"])

    for i, ev in registry.iterrows():
        pitcher = int(ev["mlbamid"])
        surgery_date = pd.Timestamp(ev["surgery_date"])

        # Exclude all windows for this pitcher near TJS except the anchor positive.
        near_mask = (
            (windows["pitcher"] == pitcher)
            & (windows["window_end_date"] >= surgery_date - pd.Timedelta(days=exclusion_before))
            & (windows["window_end_date"] <= surgery_date + pd.Timedelta(days=exclusion_after))
        )
        windows.loc[near_mask, "sample_group"] = "exclude_tjs_nearby"

        pitcher_windows = windows[windows["pitcher"] == pitcher]
        if "event_id_source_file" not in pitcher_windows.columns:
            continue
        # Positive anchors are only trusted when they come from the event-specific
        # TJS raw file. Partial league chunks can provide healthy controls, but
        # cannot prove the true last appearance before surgery by themselves.
        pitcher_windows = pitcher_windows[pitcher_windows["event_id_source_file"] == ev["event_id"]]
        if pitcher_windows.empty:
            continue
        before = pitcher_windows[pitcher_windows["window_end_date"] < surgery_date]
        if before.empty:
            continue
        anchor = before.sort_values("window_end_date").iloc[-1]
        registry.loc[i, "last_appearance_date"] = anchor["window_end_date"]
        registry.loc[i, "last_appearance_game_pk"] = anchor["window_end_game_pk"]
        registry.loc[i, "valid_window"] = True

        anchor_mask = (
            (windows["pitcher"] == pitcher)
            & (windows["window_end_game_pk"] == anchor["window_end_game_pk"])
            & (windows["event_id_source_file"] == ev["event_id"])
        )
        windows.loc[anchor_mask, "sample_group"] = "tjs"
        windows.loc[anchor_mask, "is_tjs_anchor"] = 1
        windows.loc[anchor_mask, "event_id"] = ev["event_id"]
        windows.loc[anchor_mask, "surgery_date"] = surgery_date
        windows.loc[anchor_mask, "days_to_surgery"] = (surgery_date - pd.Timestamp(anchor["window_end_date"])).days

    return windows, registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)

    interim = Path(cfg["paths"]["interim_dir"])
    processed = Path(cfg["paths"]["processed_dir"])
    processed.mkdir(parents=True, exist_ok=True)

    game_log = pd.read_csv(interim / "pitcher_game_log.csv", parse_dates=["game_date"])
    registry = pd.read_csv(interim / "tjs_registry_mlb_pitchers.csv", parse_dates=["surgery_date"])
    w = int(cfg["windows"]["window_size"])
    windows = build_windows(game_log, w=w)
    windows, registry2 = attach_tjs_labels(
        windows,
        registry,
        exclusion_before=int(cfg["windows"]["healthy_exclusion_days_before_tjs"]),
        exclusion_after=int(cfg["windows"]["healthy_exclusion_days_after_tjs"]),
    )

    windows_path = processed / "window_features.csv"
    registry_path = processed / "tjs_registry_with_anchors.csv"
    windows.to_csv(windows_path, index=False)
    registry2.to_csv(registry_path, index=False)
    print(f"Saved windows: {len(windows)} rows -> {windows_path}")
    print(windows["sample_group"].value_counts(dropna=False).to_string())
    if not windows["sample_group"].eq("healthy").any():
        print(
            "Warning: no healthy windows were created. For MTS scoring, collect league-wide "
            "control chunks with src/02b_collect_statcast_league_chunks.py or add non-nearby "
            "pitcher periods outside the TJS exclusion window."
        )
    print(f"Saved anchored registry -> {registry_path}")


if __name__ == "__main__":
    main()
