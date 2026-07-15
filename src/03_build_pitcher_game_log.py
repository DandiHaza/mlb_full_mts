from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from feature_utils import aggregate_pitcher_game


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)

    raw_base = Path(cfg["paths"]["raw_dir"])
    raw_dirs = [raw_base / "statcast_pitchers", raw_base / "statcast_league"]
    interim = Path(cfg["paths"]["interim_dir"])
    interim.mkdir(parents=True, exist_ok=True)
    files = []
    for raw_dir in raw_dirs:
        if raw_dir.exists():
            files.extend(sorted(raw_dir.glob("*.parquet")))
    if not files:
        raise FileNotFoundError("No parquet files found. Run 02_collect_statcast_for_registry.py and/or 02b_collect_statcast_league_chunks.py first.")

    logs = []
    for f in files:
        df = pd.read_parquet(f)
        game_log = aggregate_pitcher_game(df)
        # Preserve event metadata if available.
        if "event_id" in df.columns:
            game_log["event_id_source_file"] = df["event_id"].dropna().iloc[0]
        if "surgery_date" in df.columns:
            game_log["surgery_date_source_file"] = pd.to_datetime(df["surgery_date"].dropna().iloc[0])
        logs.append(game_log)

    out = pd.concat(logs, ignore_index=True)
    out = out.drop_duplicates(subset=["pitcher", "game_pk"]).sort_values(["pitcher", "game_date", "game_pk"])
    out["season"] = pd.to_datetime(out["game_date"]).dt.year
    out_path = interim / "pitcher_game_log.csv"
    out.to_csv(out_path, index=False)
    print(f"Saved pitcher-game log: {len(out)} rows -> {out_path}")


if __name__ == "__main__":
    main()
