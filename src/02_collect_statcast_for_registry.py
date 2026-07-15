from __future__ import annotations

import argparse
import os
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of registry rows for smoke test")
    parser.add_argument("--retries", type=int, default=2, help="Retries per pitcher before skipping")
    args = parser.parse_args()
    cfg = load_config(args.config)

    cache_dir = Path(cfg["paths"]["raw_dir"]) / "pybaseball_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYBASEBALL_CACHE", str(cache_dir.resolve()))

    from pybaseball import cache, statcast_pitcher
    if cfg["statcast"].get("cache_enabled", True):
        cache.enable()

    interim = Path(cfg["paths"]["interim_dir"])
    raw_dir = Path(cfg["paths"]["raw_dir"]) / "statcast_pitchers"
    raw_dir.mkdir(parents=True, exist_ok=True)

    registry = pd.read_csv(interim / "tjs_registry_mlb_pitchers.csv")
    date_col = "surgery_date" if "surgery_date" in registry.columns else "tj_surgery_date"
    registry[date_col] = pd.to_datetime(registry[date_col], errors="coerce")
    registry = registry[registry[date_col].notna() & registry["mlbamid"].notna()].copy()
    if args.limit:
        registry = registry.head(args.limit)

    lookback_days = int(cfg["statcast"]["lookback_days_before_surgery"])
    end_buffer_days = int(cfg["statcast"].get("end_buffer_days_after_surgery", 0))

    for row in tqdm(registry.itertuples(index=False), total=len(registry)):
        mlbamid = int(row.mlbamid)
        surgery_date = pd.Timestamp(getattr(row, date_col))
        start = (surgery_date - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end = (surgery_date + timedelta(days=end_buffer_days)).strftime("%Y-%m-%d")
        safe_name = str(row.player_name).replace(" ", "_").replace("/", "_")
        out_path = raw_dir / f"{row.event_id}_{mlbamid}_{safe_name}.parquet"
        if out_path.exists():
            print(f"Cache hit, keeping existing raw file: {out_path}")
            continue
        for attempt in range(1, args.retries + 2):
            try:
                df = statcast_pitcher(start_dt=start, end_dt=end, player_id=mlbamid)
                if df is None or df.empty:
                    print(f"No Statcast data: {row.event_id} {row.player_name} {mlbamid} {start}..{end}")
                    break
                df = df.copy().assign(
                    event_id=row.event_id,
                    surgery_date=surgery_date,
                    tj_surgery_date=surgery_date,
                )
                df.to_parquet(out_path, index=False)
                print(f"Saved {len(df)} rows: {out_path}")
                break
            except Exception as e:
                if attempt > args.retries:
                    print(f"Failed {row.event_id} {row.player_name} {mlbamid} after {attempt} attempts: {e}")
                else:
                    print(f"Retry {attempt}/{args.retries} for {row.event_id} {row.player_name} {mlbamid}: {e}")
                    time.sleep(2 * attempt)

    print(f"Done. Files saved under {raw_dir}")


if __name__ == "__main__":
    main()
