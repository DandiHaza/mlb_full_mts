from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
import yaml


DISPLAY_COLS = [
    "player_name",
    "mlbamid",
    "pitcher",
    "season",
    "window_start_date",
    "window_end_date",
    "sample_group",
    "D_H",
    "D_T",
    "risk_tjs",
    "alert",
]


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_threshold(reports_dir: Path) -> float | None:
    summary_path = reports_dir / "mts_summary.json"
    if not summary_path.exists():
        return None
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    threshold = summary.get("alerts", {}).get("threshold")
    return float(threshold) if threshold is not None else None


def parse_bool_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def read_scores(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"MTS score file not found: {path}")
    df = pd.read_csv(path, low_memory=False)
    for col in ["window_start_date", "window_end_date", "surgery_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["D_H", "D_T", "risk_tjs"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "alert" in df.columns:
        df["alert"] = parse_bool_series(df["alert"])
    return df


def filter_scores(
    df: pd.DataFrame,
    player_name: str | None,
    mlbamid: str | None,
    pitcher: str | None,
    as_of: str | None,
) -> pd.DataFrame:
    out = df.copy()
    if player_name:
        needle = player_name.lower()
        out = out[out["player_name"].astype(str).str.lower().str.contains(needle, na=False, regex=False)]
    if mlbamid:
        out = out[out["mlbamid"].astype(str) == str(mlbamid)]
    if pitcher:
        out = out[out["pitcher"].astype(str) == str(pitcher)]
    if as_of:
        cutoff = pd.to_datetime(as_of)
        out = out[out["window_end_date"] <= cutoff]
    return out


def format_float(value: object, digits: int = 3) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):.{digits}f}"


def relation(row: pd.Series) -> str:
    d_h = row.get("D_H")
    d_t = row.get("D_T")
    if pd.isna(d_h) or pd.isna(d_t):
        return "거리값 부족으로 가까운 reference 판단 불가"
    if d_t < d_h:
        return "TJS pre-surgery reference에 더 가까움"
    if d_h < d_t:
        return "healthy reference에 더 가까움"
    return "두 reference와의 거리가 거의 같음"


def alert_text(row: pd.Series) -> str:
    if bool(row.get("alert")):
        return "Alert=True: 기준선을 넘었으므로 검토 필요"
    return "Alert=False: 현재 기준선 미만"


def compact_table(df: pd.DataFrame, top_n: int) -> str:
    cols = [c for c in DISPLAY_COLS if c in df.columns]
    table = df[cols].head(top_n).copy()
    for col in ["D_H", "D_T", "risk_tjs"]:
        if col in table.columns:
            table[col] = table[col].map(lambda x: format_float(x))
    for col in ["window_start_date", "window_end_date"]:
        if col in table.columns:
            table[col] = pd.to_datetime(table[col], errors="coerce").dt.strftime("%Y-%m-%d")
    return table.to_string(index=False)


def safe_report_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9가-힣_-]+", "_", value).strip("_")
    return name or "player"


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description="Report latest MTS risk for a player from mts_scores.csv.")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--scores", default=None, help="Optional path to mts_scores.csv.")
    parser.add_argument("--player-name", default=None, help="Case-insensitive partial player name, e.g. Sabathia.")
    parser.add_argument("--mlbamid", default=None, help="Exact MLBAM ID.")
    parser.add_argument("--pitcher", default=None, help="Exact pitcher id used in Statcast data.")
    parser.add_argument("--as-of", default=None, help="Only use windows ending on or before this date, YYYY-MM-DD.")
    parser.add_argument("--top-n", type=int, default=10, help="Number of highest-risk windows to print.")
    parser.add_argument("--out", default=None, help="Optional CSV output path for the matched player windows.")
    args = parser.parse_args()

    if not any([args.player_name, args.mlbamid, args.pitcher]):
        raise ValueError("검색 조건이 필요합니다. --player-name, --mlbamid, --pitcher 중 하나를 입력하세요.")

    cfg = load_config(args.config)
    processed_dir = Path(cfg["paths"]["processed_dir"])
    reports_dir = Path(cfg["paths"]["reports_dir"])
    scores_path = Path(args.scores) if args.scores else processed_dir / "mts_scores.csv"
    threshold = load_threshold(reports_dir)

    df = read_scores(scores_path)
    matched = filter_scores(df, args.player_name, args.mlbamid, args.pitcher, args.as_of)
    if matched.empty:
        raise ValueError("조건에 맞는 선수 window를 찾지 못했습니다.")

    matched = matched.sort_values("window_end_date")
    latest = matched.iloc[-1]
    top_risk = matched.sort_values("risk_tjs", ascending=False)

    players = matched[["player_name", "mlbamid", "pitcher"]].drop_duplicates()
    if len(players) > 1:
        print("주의: 여러 선수가 검색되었습니다. 더 정확한 결과가 필요하면 --mlbamid를 사용하세요.")
        print(players.head(20).to_string(index=False))
        print()

    print("## Player MTS Risk Report")
    print(f"score file: {scores_path}")
    if threshold is not None:
        print(f"alert threshold: {format_float(threshold)}")
    print(f"matched windows: {len(matched)}")
    print()
    print("## Latest Window")
    print(f"player: {latest.get('player_name')} (mlbamid={latest.get('mlbamid')}, pitcher={latest.get('pitcher')})")
    print(f"window: {latest.get('window_start_date').date()} ~ {latest.get('window_end_date').date()}")
    print(f"sample_group: {latest.get('sample_group')}")
    print(f"D_H: {format_float(latest.get('D_H'))}")
    print(f"D_T: {format_float(latest.get('D_T'))}")
    print(f"risk_tjs: {format_float(latest.get('risk_tjs'))}")
    print(f"판단: {relation(latest)}")
    print(f"alert: {alert_text(latest)}")
    print()
    print(f"## Top {args.top_n} Highest-Risk Windows")
    print(compact_table(top_risk, args.top_n))

    if args.out:
        out_path = Path(args.out)
    else:
        key = args.mlbamid or args.pitcher or args.player_name or "player"
        out_path = reports_dir / f"player_risk_{safe_report_name(str(key))}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = [c for c in DISPLAY_COLS if c in matched.columns]
    matched[cols].sort_values("window_end_date").to_csv(out_path, index=False)
    print()
    print(f"Saved matched player windows -> {out_path}")


if __name__ == "__main__":
    main()
