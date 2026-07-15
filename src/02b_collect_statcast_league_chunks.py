from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def date_chunks(start: str, end: str, chunk_days: int):
    cur = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while cur <= end_ts:
        chunk_end = min(cur + pd.Timedelta(days=chunk_days - 1), end_ts)
        yield cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        cur = chunk_end + pd.Timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description="Optional league-wide Statcast collection for healthy/control windows.")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--chunk-days", type=int, default=7)
    args = parser.parse_args()
    cfg = load_config(args.config)

    cache_dir = Path(cfg["paths"]["raw_dir"]) / "pybaseball_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYBASEBALL_CACHE", str(cache_dir.resolve()))

    from pybaseball import cache, statcast
    if cfg["statcast"].get("cache_enabled", True):
        cache.enable()

    out_dir = Path(cfg["paths"]["raw_dir"]) / "statcast_league"
    out_dir.mkdir(parents=True, exist_ok=True)

    for start, end in tqdm(list(date_chunks(args.start, args.end, args.chunk_days))):
        out_path = out_dir / f"statcast_{start}_{end}.parquet"
        if out_path.exists():
            continue
        try:
            df = statcast(start_dt=start, end_dt=end)
            if df is None or df.empty:
                print(f"No rows for {start}~{end}")
                continue
            df.to_parquet(out_path, index=False)
        except Exception as e:
            print(f"Failed {start}~{end}: {e}")

    print(f"Done. League Statcast chunks saved under {out_dir}")


if __name__ == "__main__":
    main()
