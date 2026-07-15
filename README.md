# MLB-Full MTS 기반 Tommy John Surgery 경고 점수 파이프라인

이 프로젝트는 Tommy John Surgery(TJS) 전조 패턴을 탐색하기 위한 MLB-full dual-reference Mahalanobis Taguchi System(MTS) 파이프라인입니다.

이 파이프라인은 분류 모델이 아닙니다. 각 투수-window 벡터 `x`에 대해 거리 기반 경고 점수를 계산합니다.

```text
D_H(x) = healthy reference로부터의 Mahalanobis distance
D_T(x) = TJS pre-surgery reference로부터의 Mahalanobis distance
Risk_TJS(x) = log((D_H(x) + epsilon) / (D_T(x) + epsilon))
```

`Risk_TJS`가 높을수록 해당 window가 healthy reference보다 TJS pre-surgery reference 중심에 더 가깝다는 뜻입니다.

## 방법론

TJS label registry는 공개 Google Sheet인 "Tommy John Surgery List (@MLBPlayerAnalys)"를 사용합니다. Sheet의 `mlbamid` 컬럼을 MLBAM ID로 사용해 `pybaseball` Statcast 데이터와 연결합니다.

중요한 anchor 규칙은 다음과 같습니다. `TJ Surgery Date`는 label 확인용으로만 사용하며, feature window의 직접 날짜로 쓰지 않습니다. 각 TJS 이벤트에 대해 수술 전 마지막 MLB 등판을 찾고, 그 등판을 끝점으로 하는 직전 10경기 window를 positive TJS window로 만듭니다.

MTS 구현은 healthy window로 scaling과 covariance를 학습합니다. 이후 healthy 중심과 TJS pre-surgery 중심까지의 거리를 각각 계산합니다. covariance는 healthy reference에서 추정한 shrinkage covariance 하나만 사용하며, 기본값은 `oas`입니다.

## 설치

Python 3.10 이상이 필요합니다. 현재 workspace에서는 Python 3.12로 검증했습니다.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
```

venv 생성 중 pip bootstrap이 실패하거나 디스크 공간 문제가 생기면 공간을 확보한 뒤 다시 시도하세요. 이 workspace에서는 한 번 pip cache를 비워야 했습니다.

```powershell
python -m pip cache purge
```

## 최소 첫 실행

Statcast 데이터를 크게 받기 전에 synthetic smoke test와 TJS registry build부터 확인하세요.

```powershell
.venv\Scripts\python.exe tests\smoke_test_synthetic.py
.venv\Scripts\python.exe src\01_build_tjs_registry.py --config config\config.yaml
.venv\Scripts\python.exe src\02_collect_statcast_for_registry.py --config config\config.yaml --limit 5
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
```

마지막 MTS command는 healthy/control window가 있어야 정상적으로 점수를 저장합니다. `--limit 5` TJS pre-surgery 샘플만 있는 상태에서는 아래 메시지와 함께 멈추는 것이 정상입니다.

```text
No healthy windows are available.
```

`mts_scores.csv`를 만들려면 먼저 league-wide control chunk를 추가로 수집해야 합니다.

## 작은 Statcast 샘플

Registry 기반 Statcast collector는 `--limit` 옵션을 지원합니다. 각 TJS 이벤트마다 raw parquet 파일 하나를 아래 경로에 저장합니다.

```text
data/raw/statcast_pitchers/
```

이미 존재하는 raw parquet 파일은 덮어쓰지 않고 건너뜁니다. 기본 수집 구간은 `tj_surgery_date` 기준 400일 전부터 수술일까지입니다.

## Healthy Control 데이터

Healthy reference window를 만들려면 작은 league-wide Statcast chunk부터 수집하세요.

```powershell
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-04-01 --end 2019-04-07 --chunk-days 3
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
```

처음에는 짧은 날짜 범위로 시작하세요. row 수와 디스크 사용량을 확인한 뒤에만 범위를 넓히는 편이 안전합니다.

현재 workspace에서는 TJS registry 상위 75개 이벤트 중 Statcast data와 valid 10-game anchor가 있는 71개 이벤트와 2019년 4~6월 league-wide chunk를 사용해 MTS scoring까지 완료했습니다. 생성된 score 파일은 `data/processed/mts_scores.csv`이고, summary 파일은 `reports/mts_summary.json`입니다.

현재 최소 실행 결과:

```text
healthy windows: 5529
TJS windows: 71
scored rows: 5600
roc_auc: 0.8948463797798548
pr_auc: 0.3439362931019851
```

이 결과는 pipeline end-to-end 동작 확인용입니다. Healthy reference가 2019년 4~6월 세 달치 league chunk에 기반하므로 이전보다 안정적이지만, 연구용 해석이나 threshold 판단에는 아직 추가 검증이 필요합니다.

## Full Run 주의

Statcast full-season 데이터를 한 번에 받지 마세요. 다운로드가 느리고, 파일이 커질 수 있으며, rate limit에 걸릴 수 있습니다. 작은 날짜 chunk로 나누어 수집하고, output을 확인하면서 확장하세요. Raw data 파일은 재사용 가능하므로 불필요하게 덮어쓰지 않는 것이 좋습니다.

## 출력 파일

```text
data/interim/tjs_registry_mlb_pitchers.csv
data/raw/statcast_pitchers/*.parquet
data/raw/statcast_league/*.parquet
data/interim/pitcher_game_log.csv
data/processed/window_features.csv
data/processed/tjs_registry_with_anchors.csv
data/processed/mts_scores.csv
reports/mts_summary.json
```

`mts_scores.csv`와 `reports/mts_summary.json`은 healthy window와 TJS window가 모두 있을 때만 생성됩니다.

## 현재 한계

이 결과는 calibrated classifier가 아니라 거리 기반 exploratory warning score입니다.

`TJ Surgery Date`는 label 확인용으로 사용하지만, positive window anchor는 수술 전 마지막 등판일입니다.

Healthy reference의 품질은 league-wide control 데이터 품질에 크게 의존합니다. TJS-only smoke sample은 pipeline debugging에는 유용하지만 최종 scoring에는 충분하지 않습니다.

MLB-full Statcast feature가 KBO에 그대로 이전된다고 가정하면 안 됩니다. 이후 MLB-KBO-compatible reduced feature set을 별도로 테스트해야 합니다.
