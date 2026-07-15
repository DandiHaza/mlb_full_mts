from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\n", "_", regex=False)
        .str.replace(" ", "_", regex=False)
        .str.replace("/", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.replace("%", "pct", regex=False)
        .str.replace("(", "", regex=False)
        .str.replace(")", "", regex=False)
        .str.lower()
    )
    return df


def first_existing(columns: list[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def build_registry(cfg: dict) -> tuple[pd.DataFrame, dict]:
    url = cfg["paths"]["tjs_sheet_csv_url"]
    # First row is donation line; second row is real header.
    raw = pd.read_csv(url, header=1)
    raw = normalize_columns(raw)
    total_rows = len(raw)

    # Expected normalized columns include player, tj_surgery_date, team, level,
    # position, throws, age, mlbamid, fgid, and surgeon/surgeons.
    out = raw.copy()
    rename_map = {}
    player_col = first_existing(list(out.columns), ["player", "name", "player_name"])
    surgery_col = first_existing(list(out.columns), ["tj_surgery_date", "surgery_date", "date"])
    surgeon_col = first_existing(list(out.columns), ["surgeon", "surgeons"])
    if player_col:
        rename_map[player_col] = "player_name"
    if surgery_col:
        rename_map[surgery_col] = "tj_surgery_date"
    if surgeon_col:
        rename_map[surgeon_col] = "surgeon"
    out = out.rename(columns=rename_map)

    required = ["player_name", "tj_surgery_date", "position", "level", "mlbamid"]
    missing_required = [c for c in required if c not in out.columns]
    if missing_required:
        raise KeyError(f"TJS sheet is missing expected columns after normalization: {missing_required}")

    out["tj_surgery_date"] = pd.to_datetime(out["tj_surgery_date"], errors="coerce")
    out["surgery_date"] = out["tj_surgery_date"]
    out["surgery_year"] = out["tj_surgery_date"].dt.year
    out["mlbamid"] = pd.to_numeric(out.get("mlbamid"), errors="coerce").astype("Int64")

    reg_cfg = cfg["registry"]
    out = out[out["tj_surgery_date"].notna()]
    if reg_cfg.get("position_filter"):
        out = out[out["position"].astype(str).str.upper() == reg_cfg["position_filter"].upper()]
    pitcher_rows = len(out)
    if reg_cfg.get("level_filter"):
        out = out[out["level"].astype(str).str.upper() == reg_cfg["level_filter"].upper()]
    mlb_pitcher_rows = len(out)
    valid_mlbamid_rows = int(out["mlbamid"].notna().sum())
    missing_mlbamid_rows = int(out["mlbamid"].isna().sum())
    if reg_cfg.get("require_mlbamid", True):
        out = out[out["mlbamid"].notna()]
    out = out[out["surgery_year"].between(reg_cfg["min_year"], reg_cfg["max_year"])]

    keep_cols = [c for c in [
        "player_name", "tj_surgery_date", "surgery_date", "surgery_year", "team", "level", "position", "throws",
        "country", "age", "return_date_same_level", "recovery_time_months", "mlbamid", "fgid", "surgeon",
        "active", "year", "month", "day",
    ] if c in out.columns]
    out = out[keep_cols].drop_duplicates().sort_values(["surgery_date", "player_name"]).reset_index(drop=True)
    out["event_id"] = [f"TJS_{i:05d}" for i in range(1, len(out) + 1)]
    # Move event_id first.
    cols = ["event_id"] + [c for c in out.columns if c != "event_id"]
    stats = {
        "total_rows_loaded": total_rows,
        "pitcher_rows_retained": pitcher_rows,
        "mlb_level_pitcher_rows_retained": mlb_pitcher_rows,
        "rows_with_valid_mlbamid": valid_mlbamid_rows,
        "rows_with_missing_mlbamid": missing_mlbamid_rows,
        "final_rows_saved": len(out),
    }
    return out[cols], stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    out_dir = Path(cfg["paths"]["interim_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    registry, stats = build_registry(cfg)
    out_path = out_dir / "tjs_registry_mlb_pitchers.csv"
    registry.to_csv(out_path, index=False)
    print("Registry build diagnostics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print(f"Saved {len(registry)} MLB pitcher TJS events to {out_path}")
    print(registry.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
