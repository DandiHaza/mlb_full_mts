from __future__ import annotations

import numpy as np
import pandas as pd


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator is None or pd.isna(denominator) or denominator == 0:
        return np.nan
    return numerator / denominator


def linear_slope(values) -> float:
    """Return slope over ordered values using x = 0..n-1."""
    arr = pd.Series(values).astype(float).dropna().to_numpy()
    if len(arr) < 2:
        return np.nan
    x = np.arange(len(arr), dtype=float)
    x = x - x.mean()
    y = arr - arr.mean()
    denom = np.sum(x ** 2)
    if denom == 0:
        return np.nan
    return float(np.sum(x * y) / denom)


def event_rate(df: pd.DataFrame, event_names: set[str]) -> float:
    """Rate by unique batter faced proxy: unique PA rows via at_bat_number within pitcher-game."""
    if df.empty:
        return np.nan
    tbf = df["pa_key"].nunique() if "pa_key" in df.columns else df["at_bat_number"].nunique()
    if tbf == 0:
        return np.nan
    return float(df["events"].isin(event_names).sum() / tbf)


def pitch_type_share(game_df: pd.DataFrame, pitch_type: str) -> float:
    if "pitch_type" not in game_df.columns:
        return np.nan
    total = len(game_df)
    if total == 0:
        return np.nan
    return float((game_df["pitch_type"] == pitch_type).sum() / total)


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            df[col] = np.nan
    return df


def first_non_null(series: pd.Series):
    vals = series.dropna()
    return vals.iloc[0] if not vals.empty else None


def aggregate_pitcher_game(statcast: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pitch-level Statcast data to one row per pitcher-game.

    Expected Statcast columns include:
    pitcher, player_name, game_pk, game_date, pitch_type, release_speed,
    release_spin_rate, release_extension, release_pos_x, release_pos_z,
    pfx_x, pfx_z, zone, description, events, at_bat_number.
    """
    df = ensure_columns(statcast, [
        "pitcher", "player_name", "game_pk", "game_date", "pitch_type", "release_speed",
        "release_spin_rate", "release_extension", "release_pos_x", "release_pos_z",
        "pfx_x", "pfx_z", "zone", "description", "events", "at_bat_number",
        "pitch_number", "p_throws",
    ])
    missing_required = [c for c in ["pitcher", "game_pk", "game_date"] if df[c].isna().all()]
    if missing_required:
        raise ValueError(f"Statcast data is missing required game-log columns: {missing_required}")

    df["game_date"] = pd.to_datetime(df["game_date"])
    numeric_cols = [
        "pitcher", "game_pk", "release_speed", "release_spin_rate", "release_extension",
        "release_pos_x", "release_pos_z", "pfx_x", "pfx_z", "zone", "at_bat_number",
        "pitch_number",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["pa_key"] = df["game_pk"].astype(str) + "_" + df["pitcher"].astype(str) + "_" + df["at_bat_number"].astype(str)

    strikeout_events = {"strikeout", "strikeout_double_play"}
    walk_events = {"walk", "intent_walk"}
    hr_events = {"home_run"}
    whiff_desc = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}
    called_strike_desc = {"called_strike"}

    rows = []
    group_cols = ["pitcher", "game_pk"]
    for (pitcher, game_pk), g in df.groupby(group_cols, sort=False):
        g = g.sort_values(["game_date", "at_bat_number", "pitch_number"])
        pitch_count = len(g)
        if g["at_bat_number"].notna().any():
            tbf = g["pa_key"].nunique()
        else:
            tbf = np.nan
        pitch_types = g["pitch_type"].dropna()
        row = {
            "pitcher": int(pitcher),
            "game_pk": game_pk,
            "game_date": g["game_date"].iloc[0],
            "player_name": first_non_null(g["player_name"]),
            "p_throws": first_non_null(g["p_throws"]),
            "pitch_count": pitch_count,
            "tbf": tbf,
            "release_speed_mean": g["release_speed"].mean(),
            "release_speed_std": g["release_speed"].std(),
            "release_speed_sd": g["release_speed"].std(),
            "release_spin_rate_mean": g["release_spin_rate"].mean(),
            "release_spin_rate_std": g["release_spin_rate"].std(),
            "release_spin_rate_sd": g["release_spin_rate"].std(),
            "release_extension_mean": g["release_extension"].mean(),
            "release_pos_x_mean": g["release_pos_x"].mean(),
            "release_pos_z_mean": g["release_pos_z"].mean(),
            "release_pos_x_std": g["release_pos_x"].std(),
            "release_pos_z_std": g["release_pos_z"].std(),
            "release_pos_x_sd": g["release_pos_x"].std(),
            "release_pos_z_sd": g["release_pos_z"].std(),
            "pfx_x_mean": g["pfx_x"].mean(),
            "pfx_z_mean": g["pfx_z"].mean(),
            "zone_rate": safe_divide(g["zone"].between(1, 9).sum(), pitch_count),
            "whiff_rate": safe_divide(g["description"].isin(whiff_desc).sum(), pitch_count),
            "called_strike_rate": safe_divide(g["description"].isin(called_strike_desc).sum(), pitch_count),
            "k_rate": safe_divide(g["events"].isin(strikeout_events).sum(), tbf),
            "bb_rate": safe_divide(g["events"].isin(walk_events).sum(), tbf),
            "hr_rate": safe_divide(g["events"].isin(hr_events).sum(), tbf),
        }
        for pt in ["FF", "SI", "FC", "SL", "ST", "CU", "KC", "CH", "FS"]:
            row[f"{pt.lower()}_share"] = pitch_type_share(g, pt)

        fb = g[g["pitch_type"].isin(["FF", "SI", "FC"])]
        row["fb_release_speed_mean"] = fb["release_speed"].mean() if len(fb) else np.nan
        row["fb_release_spin_rate_mean"] = fb["release_spin_rate"].mean() if len(fb) else np.nan
        row["primary_pitch_type"] = pitch_types.mode().iloc[0] if not pitch_types.empty else None
        rows.append(row)

    out = pd.DataFrame(rows)
    out = out.sort_values(["pitcher", "game_date", "game_pk"]).reset_index(drop=True)
    out["rest_days"] = out.groupby("pitcher")["game_date"].diff().dt.days
    return out
