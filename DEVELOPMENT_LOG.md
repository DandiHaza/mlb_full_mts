# 개발 로그

날짜: 2026-07-08

## 수정한 내용

- 로컬 `.venv`를 만들고 Python 3.12 환경에서 requirements를 설치했습니다.
- 깨진 문자(mojibake)가 있던 README를 정리하고, 설치법, 최소 실행 절차, full run 주의사항을 다시 작성했습니다.
- `config/config.yaml`을 정리하고, MTS feature 이름을 10경기 rolling window output과 맞췄습니다.
- Registry build를 다음처럼 수정했습니다.
  - `tj_surgery_date`와 호환용 `surgery_date`를 함께 유지
  - `player_name`, `team`, `level`, `position`, `throws`, `age`, `mlbamid`, `fgid`, `surgeon`, `year`, `month`, `day` 유지
  - 전체 row 수, 투수 row 수, MLB-level 투수 row 수, 유효 MLBAM ID 수, missing MLBAM ID 수를 출력
- Statcast collection을 다음처럼 수정했습니다.
  - `--limit` 지원
  - 수술 전 400일 구간 사용
  - TJS 이벤트별 raw parquet 파일 하나씩 저장
  - 기존 raw 파일은 덮어쓰지 않고 skip
  - player 단위 실패 시 retry 후 다음 player로 진행
  - pybaseball cache를 `data/raw/pybaseball_cache` 아래로 이동
- Pitcher-game aggregation이 optional Statcast column 누락에도 버티도록 보강했습니다.
- Game-log output에 `release_speed_std`, `release_spin_rate_std`, `release_pos_x_std`, `release_pos_z_std` 같은 alias를 추가했습니다.
- Rolling window output이 `pitch_count_sum_10`, `release_speed_slope_10`, `zone_rate_10` 같은 canonical `_10` feature를 내도록 수정했습니다.
- Window output에 `mlbamid`, `window_size`, `sample_group`, event-source metadata를 추가했습니다.
- 같은 선수가 여러 TJS 이벤트를 가진 경우 잘못된 anchor가 붙을 수 있는 문제를 고쳤습니다. TJS event metadata가 있으면 positive anchor가 `event_id_source_file`과 일치해야 합니다.
- MTS scoring을 다음처럼 수정했습니다.
  - squared distance가 아니라 실제 Mahalanobis distance 사용
  - healthy-reference covariance 하나만 사용
  - missing/all-empty feature를 diagnostic과 함께 skip
  - healthy 또는 TJS reference window가 없으면 명확한 오류로 중단
  - scoring 가능 시 risk 상위 20개 window 출력

## 실행한 명령

```powershell
python --version
python tests\smoke_test_synthetic.py
python -m venv .venv
python -m pip --python .venv\Scripts\python.exe install -r requirements.txt
python -m pip cache purge
python -m venv .venv
.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.venv\Scripts\python.exe tests\smoke_test_synthetic.py
.venv\Scripts\python.exe src\01_build_tjs_registry.py --config config\config.yaml
.venv\Scripts\python.exe src\02_collect_statcast_for_registry.py --config config\config.yaml --limit 5
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

## 생성된 출력

- `data/interim/tjs_registry_mlb_pitchers.csv`
  - MLB pitcher TJS event 251개
  - diagnostics: 전체 2706 rows, pitcher rows 2480개, MLB-level pitcher rows 632개, 유효 MLBAM ID 631개, missing MLBAM ID 1개
- `data/raw/statcast_pitchers/TJS_00001_623406_Shae_Simmons.parquet`
  - 414 rows
- `data/raw/statcast_pitchers/TJS_00002_592238_Brandon_Cumpton_.parquet`
  - 1250 rows
- `data/raw/statcast_pitchers/TJS_00003_525768_Tim_Collins.parquet`
  - 609 rows
- `data/raw/statcast_pitchers/TJS_00004_572831_Josh_Edgin.parquet`
  - 451 rows
- `data/raw/statcast_pitchers/TJS_00005_506433_Yu_Darvish.parquet`
  - 2518 rows
- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 170개
  - `pitcher, game_pk` 중복 0개
- `data/processed/window_features.csv`
  - window 125개
  - TJS anchor window 5개
  - near-TJS excluded window 120개
  - healthy window 0개
- `data/processed/tjs_registry_with_anchors.csv`
  - 의도적으로 다운로드한 5개 TJS event에 대해 valid anchor 5개

## 실패한 내용과 이유

- 첫 smoke test는 active Python environment에 `pandas`가 없어서 실패했습니다.
- 첫 venv 생성은 `ensurepip` 단계에서 실패했습니다. pip cache 공간을 확보한 뒤 venv 생성에 성공했습니다.
- 첫 dependency install은 `No space left on device`로 실패했습니다. pip cache를 지우고 `--no-cache-dir`로 다시 설치해 해결했습니다.
- 첫 registry build는 Google Sheets 접근이 sandbox network 제한에 막혀 실패했습니다. network approval 후 같은 명령을 다시 실행해 성공했습니다.
- 첫 Statcast collection은 pybaseball이 `C:\Users\user\.pybaseball`에 cache directory를 만들려고 해서 실패했습니다. `PYBASEBALL_CACHE`를 `data/raw/pybaseball_cache`로 지정해 해결했습니다.
- Statcast collection은 이후 Baseball Savant network 접근 승인이 필요했습니다. `--limit 5` 명령을 승인 후 다시 실행해 성공했습니다.
- MTS scoring은 `mts_scores.csv`를 만들지 않았습니다. 이유는 tiny TJS-only sample에 healthy/control window가 없기 때문입니다. 현재 script는 healthy reference 없이 조용히 진행하지 않고 명확한 오류로 중단합니다.

## 다음 권장 단계

작은 league-wide healthy/control chunk를 먼저 수집한 뒤, game log, window, score를 다시 만드세요.

```powershell
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-04-01 --end 2019-04-07 --chunk-days 3
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
```

## 추가 진행: 최소 MTS scoring 완료

사용자 요청에 따라 다음 단계까지 진행했습니다. 먼저 2019-04-01부터 2019-04-07까지 작은 league-wide control chunk를 받았지만 healthy window가 1개만 생성되어 reference로 부족했습니다. 이후 full-season이 아니라 2019년 4월 나머지 구간만 추가로 받았습니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-04-01 --end 2019-04-07 --chunk-days 3
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-04-08 --end 2019-04-30 --chunk-days 3
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
```

추가 생성된 league raw files:

```text
data/raw/statcast_league/statcast_2019-04-01_2019-04-03.parquet
data/raw/statcast_league/statcast_2019-04-04_2019-04-06.parquet
data/raw/statcast_league/statcast_2019-04-07_2019-04-07.parquet
data/raw/statcast_league/statcast_2019-04-08_2019-04-10.parquet
data/raw/statcast_league/statcast_2019-04-11_2019-04-13.parquet
data/raw/statcast_league/statcast_2019-04-14_2019-04-16.parquet
data/raw/statcast_league/statcast_2019-04-17_2019-04-19.parquet
data/raw/statcast_league/statcast_2019-04-20_2019-04-22.parquet
data/raw/statcast_league/statcast_2019-04-23_2019-04-25.parquet
data/raw/statcast_league/statcast_2019-04-26_2019-04-28.parquet
data/raw/statcast_league/statcast_2019-04-29_2019-04-30.parquet
```

최종 최소 실행 결과:

- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 3496개
- `data/processed/window_features.csv`
  - 전체 window 498개
  - healthy window 366개
  - near-TJS excluded window 127개
  - TJS anchor window 5개
- `data/processed/mts_scores.csv`
  - scored row 371개
  - healthy 366개, TJS 5개
- `reports/mts_summary.json`
  - healthy windows 366개
  - TJS windows 5개
  - missing/skipped feature column 없음

중간에 발견한 문제:

- Partial league chunk만 보고 TJS registry event에 positive anchor가 붙을 수 있었습니다. 이는 실제 "수술 전 마지막 등판"을 보장하지 못하므로 위험합니다.
- `src/04_build_windows.py`를 수정해 positive TJS anchor는 event-specific TJS raw file의 `event_id_source_file`과 일치할 때만 붙도록 했습니다.
- League chunk에 섞인 TJS registry 선수의 수술 근처 window는 healthy에서 제외되도록 유지했습니다.
- `src/05_run_mts.py`는 MTS score 저장 후 top 20 출력에서 Windows console encoding 문제로 한 번 실패했습니다. 출력 error handling을 보강해 정상 종료되도록 수정했습니다.

현재 상태:

- 최소 end-to-end MTS scoring은 완료됐습니다.
- 단, healthy reference는 2019년 4월 한 달치 league chunk에 기반한 smoke/reference sample입니다.
- 연구용으로 해석하려면 여러 season의 league-wide healthy/control data를 더 체계적으로 수집하고, TJS event별 pre-surgery raw coverage도 확장해야 합니다.

## 추가 진행: TJS sample을 20개 이벤트까지 확장

사용자 요청에 따라 다음 단계로 TJS registry 상위 20개 이벤트까지 pre-surgery Statcast collection을 확장했습니다. 기존 5개 raw file은 cache hit로 보존했고, `TJS_00006` Joel Hanrahan은 해당 구간에서 Statcast row가 없어 raw file이 생성되지 않았습니다. 나머지 이벤트는 event별 parquet로 저장됐습니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02_collect_statcast_for_registry.py --config config\config.yaml --limit 20
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

추가 결과:

- `data/raw/statcast_pitchers/`
  - 총 19개 TJS event parquet file
  - `TJS_00006`은 "No Statcast data"로 skip
- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 4103개
- `data/processed/window_features.csv`
  - 전체 window 1011개
  - healthy window 411개
  - near-TJS excluded window 581개
  - TJS anchor window 19개
- `data/processed/tjs_registry_with_anchors.csv`
  - valid TJS anchor 19개
- `data/processed/mts_scores.csv`
  - scored row 430개
  - healthy 411개
  - TJS 19개
- `reports/mts_summary.json`
  - `roc_auc`: 0.8629786144192598
  - `pr_auc`: 0.44407633043252936

현재 해석:

- 최소 동작 모델은 TJS 19개 anchor까지 확장되어 이전보다 안정적입니다.
- 그래도 healthy reference는 아직 2019년 4월 한 달치이므로, 최종 연구용 기준선으로 보기는 어렵습니다.
- 다음 단계는 TJS limit을 50 정도로 늘리거나, healthy/control 기간을 2019년 여러 달로 넓히는 것입니다. 둘 다 한 번에 크게 늘리기보다는 작은 chunk 단위로 진행하는 편이 안전합니다.

## 추가 진행: healthy/control reference를 2019년 5월까지 확장

사용자 요청에 따라 다음 단계로 healthy/control reference를 확장했습니다. 기존 2019년 4월 league-wide chunk에 2019년 5월 전체를 3일 chunk 단위로 추가했습니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-05-01 --end 2019-05-31 --chunk-days 3
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

추가 결과:

- `data/raw/statcast_league/`
  - league chunk parquet file 총 22개
- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 7566개
- `data/processed/window_features.csv`
  - 전체 window 3199개
  - healthy window 2546개
  - near-TJS excluded window 634개
  - TJS anchor window 19개
- `data/processed/mts_scores.csv`
  - scored row 2565개
  - healthy 2546개
  - TJS 19개
- `reports/mts_summary.json`
  - `roc_auc`: 0.9075329722578245
  - `pr_auc`: 0.431207970809458
  - missing/skipped feature column 없음

현재 해석:

- Healthy reference가 411개에서 2546개로 늘어 이전보다 훨씬 안정적인 smoke/reference sample이 됐습니다.
- Top-risk 상위권에 TJS anchor가 여러 개 올라오므로 pipeline 신호 방향은 일단 합리적으로 보입니다.
- 하지만 여전히 2019년 4~5월 두 달치 control sample과 TJS 19개 anchor 기반입니다. 최종 연구용 모델로 보려면 여러 season의 control data와 더 많은 TJS event coverage가 필요합니다.

## 추가 진행: TJS sample을 50개 이벤트까지 확장

사용자 요청에 따라 TJS registry 상위 50개 이벤트까지 pre-surgery Statcast collection을 확장했습니다. 기존 raw parquet는 cache hit로 보존했고, 새 이벤트만 추가 다운로드했습니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02_collect_statcast_for_registry.py --config config\config.yaml --limit 50
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

추가 결과:

- `data/raw/statcast_pitchers/`
  - 총 48개 TJS event parquet file
  - `TJS_00006` Joel Hanrahan: 해당 구간 Statcast row 없음
  - `TJS_00030` Tim Collins 두 번째 이벤트: 해당 구간 Statcast row 없음
- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 8627개
- `data/processed/window_features.csv`
  - 전체 window 4106개
  - healthy window 2664개
  - near-TJS excluded window 1395개
  - TJS anchor window 47개
- `data/processed/tjs_registry_with_anchors.csv`
  - valid TJS anchor 47개
- `data/processed/mts_scores.csv`
  - scored row 2711개
  - healthy 2664개
  - TJS 47개
- `reports/mts_summary.json`
  - `roc_auc`: 0.9064436777202735
  - `pr_auc`: 0.434422283586421
  - missing/skipped feature column 없음

현재 해석:

- TJS anchor가 19개에서 47개로 늘어 positive reference가 이전보다 더 안정적입니다.
- Top-risk 상위 10개 중 다수가 TJS anchor로 나타나며, signal 방향은 유지됩니다.
- Healthy reference는 여전히 2019년 4~5월 두 달치입니다. 다음 확장은 healthy/control 기간을 2019년 6월 이후로 넓히는 방향이 좋습니다.

## 추가 진행: TJS 75개 이벤트와 2019년 6월 control까지 확장

사용자 요청에 따라 가능한 범위에서 한 단계 더 크게 확장했습니다. Full run은 피하고, TJS는 registry 상위 75개 이벤트까지, healthy/control은 2019년 6월 league-wide chunk까지 추가했습니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02_collect_statcast_for_registry.py --config config\config.yaml --limit 75
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-06-01 --end 2019-06-30 --chunk-days 3
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
```

추가 결과:

- `data/raw/statcast_pitchers/`
  - TJS event parquet file 총 73개
  - 상위 75개 registry event 중 일부는 Statcast row 없음 또는 valid 10-game anchor 없음
- `data/raw/statcast_league/`
  - league chunk parquet file 총 32개
  - 2019년 4~6월 control data 포함
- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 13035개
- `data/processed/window_features.csv`
  - 전체 window 7803개
  - healthy window 5529개
  - near-TJS excluded window 2203개
  - TJS anchor window 71개
- `data/processed/tjs_registry_with_anchors.csv`
  - valid TJS anchor 71개
- `data/processed/mts_scores.csv`
  - scored row 5600개
  - healthy 5529개
  - TJS 71개
- `reports/mts_summary.json`
  - `roc_auc`: 0.8948463797798548
  - `pr_auc`: 0.3439362931019851
  - missing/skipped feature column 없음

현재 해석:

- TJS positive reference는 47개에서 71개 anchor로 늘었습니다.
- Healthy reference는 2664개에서 5529개 window로 늘었습니다.
- ROC-AUC는 0.9064에서 0.8948로 소폭 내려갔지만, sample이 커지고 더 다양한 pitcher/window가 들어오면서 더 현실적인 검증값으로 안정화되는 흐름으로 볼 수 있습니다.
- PR-AUC도 0.4344에서 0.3439로 내려갔습니다. positive가 여전히 적고 healthy가 크게 늘어난 불균형 상황이므로 threshold 해석은 아직 조심해야 합니다.
- Top-risk 상위권에는 여전히 TJS anchor가 다수 포함되어 있어 `Risk_TJS` 방향성은 유지됩니다.

다음 권장 작업:

- 2019년 7~9월 control chunk를 추가해 healthy reference를 한 시즌에 가깝게 확장
- TJS sample을 100개 이벤트까지 확장
- season/year confounding 검사를 위한 holdout 또는 season-stratified diagnostic 추가
- top-risk healthy false positive를 별도 CSV로 저장해 수동 검토

## 추가 진행: MTS 결측치 보정 기준을 healthy reference로 고정

날짜: 2026-07-09

이전 진단에서 발견한 leakage 위험을 먼저 줄였습니다. 기존 `prepare_feature_matrix()`는 scoring 대상인 healthy와 TJS window를 모두 섞은 전체 matrix의 median으로 결측치를 채웠습니다. 이 방식은 TJS reference 정보가 전처리 단계에 섞일 수 있으므로, MTS 모델의 원칙과 완전히 맞지 않았습니다.

수정한 내용:

- `src/mts_utils.py`
  - numeric 변환과 inf 제거를 담당하는 `coerce_feature_matrix()` 추가
  - reference median을 fit하는 `fit_feature_medians()` 추가
  - `prepare_feature_matrix()`가 외부에서 받은 `impute_values`를 사용할 수 있도록 확장
  - 기존 호출 방식도 유지해 synthetic smoke test와 호환되도록 처리
- `src/05_run_mts.py`
  - imputation median을 healthy window에서만 fit하도록 변경
  - healthy reference에서 전부 missing인 feature는 별도로 skip
  - `reports/mts_summary.json`에 `imputation_reference: healthy_median` 기록

실행한 명령:

```powershell
.venv\Scripts\python.exe tests\smoke_test_synthetic.py
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

검증 결과:

- synthetic smoke test 통과
- MTS scoring 정상 완료
- compileall 정상 완료
- 현재 scoring 기준:
  - healthy windows: 5529개
  - TJS windows: 71개
  - missing/skipped feature column 없음

현재 해석:

- MTS covariance와 scaler는 기존처럼 healthy reference만으로 fit됩니다.
- 결측치 보정도 healthy reference 기준으로 바뀌어, TJS reference가 전처리 median에 영향을 주는 위험을 줄였습니다.
- 기존 결과와 score 값은 아주 작게 달라질 수 있습니다. 이는 결측치 median 기준이 바뀐 데 따른 정상적인 변화입니다.

## 추가 진행: TJS 100개 이벤트와 2019년 7월 control까지 확장

날짜: 2026-07-09

다음 단계로 TJS positive coverage와 healthy/control reference를 한 단계 더 확장했습니다. 한 번에 2019년 7~9월 전체를 받지는 않고, 우선 TJS registry 상위 100개 이벤트와 2019년 7월 league-wide control만 추가했습니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02_collect_statcast_for_registry.py --config config\config.yaml --limit 100
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-07-01 --end 2019-07-31 --chunk-days 3
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

추가 수집 결과:

- `data/raw/statcast_pitchers/`
  - TJS event parquet file 총 98개
  - `TJS_00006` Joel Hanrahan과 `TJS_00030` Tim Collins 두 번째 이벤트는 해당 구간 Statcast row가 없어 계속 skip
  - `TJS_00076`부터 `TJS_00100`까지 새 raw parquet 저장 완료
- `data/raw/statcast_league/`
  - league chunk parquet file 총 43개
  - 2019년 4~7월 control data 포함

재생성 결과:

- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 17016개
- `data/processed/window_features.csv`
  - 전체 window 11226개
  - healthy window 8259개
  - near-TJS excluded window 2872개
  - TJS anchor window 95개
- `data/processed/tjs_registry_with_anchors.csv`
  - valid TJS anchor 95개
- `data/processed/mts_scores.csv`
  - scored row 8354개
  - healthy 8259개
  - TJS 95개
- `reports/mts_summary.json`
  - `roc_auc`: 0.896416668259825
  - `pr_auc`: 0.34297808830460336
  - `imputation_reference`: `healthy_median`
  - missing/skipped feature column 없음

추가 진단 파일:

- `reports/healthy_alert_windows.csv`
  - healthy 중 threshold 이상 alert window 413개
  - high-risk healthy false positive 수동 검토용
- `reports/tjs_anchor_ranked_windows.csv`
  - TJS anchor 95개를 `risk_tjs` 내림차순으로 저장

수정한 내용:

- `src/05_run_mts.py`
  - scoring output에 `alert` column 추가
  - threshold 이상 healthy window를 `reports/healthy_alert_windows.csv`로 저장
  - TJS anchor ranking을 `reports/tjs_anchor_ranked_windows.csv`로 저장

현재 해석:

- TJS positive reference는 71개에서 95개 anchor로 늘었습니다.
- Healthy reference는 5529개에서 8259개 window로 늘었습니다.
- ROC-AUC는 0.8954에서 0.8964로 거의 유지됐고, PR-AUC는 0.3436에서 0.3430으로 거의 비슷합니다.
- sample이 커졌는데도 signal 방향이 유지되고 있어 pipeline은 안정적으로 보입니다.
- 다만 false alert가 413개로 늘었고, 상위 healthy alert에 특정 pitcher가 반복적으로 나타납니다. 다음 단계에서는 `reports/healthy_alert_windows.csv`를 보고 실제 false positive 유형을 분류하는 것이 좋습니다.

다음 권장 작업:

- 2019년 8~9월 control chunk를 추가해 healthy reference를 정규시즌 대부분으로 확장
- TJS sample을 125개 또는 150개 이벤트까지 점진 확장
- `healthy_alert_windows.csv`에서 pitcher별 반복 alert, 복귀 직후/부상 이력/role change 여부를 수동 검토
- season/year confounding 진단을 위해 TJS 연도와 control 연도를 나눈 summary 추가

## 추가 진행: 2019년 8~9월 control 추가

날짜: 2026-07-09

사용자 요청에 따라 TJS sample은 그대로 두고, healthy/control reference만 2019년 8월부터 9월까지 추가했습니다. 이로써 현재 league-wide healthy/control은 2019년 4월부터 9월까지 포함합니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-08-01 --end 2019-09-30 --chunk-days 3
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2019-08-25 --end 2019-08-27 --chunk-days 1
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

수집 중 특이사항:

- 최초 3일 chunk 수집에서 `2019-08-25~2019-08-27` 구간은 Baseball Savant CSV parsing 오류로 실패했습니다.
- 같은 구간을 `--chunk-days 1`로 재시도해 `2019-08-25`, `2019-08-26`, `2019-08-27` parquet를 모두 저장했습니다.
- `2019-09-30`은 "No rows"로 기록되어 parquet가 생성되지 않았습니다.

현재 raw data 상태:

- `data/raw/statcast_pitchers/`
  - TJS event parquet file 총 98개
- `data/raw/statcast_league/`
  - league chunk parquet file 총 65개
  - 2019년 4~9월 control data 포함

재생성 결과:

- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 24585개
- `data/processed/window_features.csv`
  - 전체 window 17827개
  - healthy window 14704개
  - near-TJS excluded window 3028개
  - TJS anchor window 95개
- `data/processed/tjs_registry_with_anchors.csv`
  - valid TJS anchor 95개
- `data/processed/mts_scores.csv`
  - scored row 14799개
  - healthy 14704개
  - TJS 95개
- `reports/mts_summary.json`
  - `roc_auc`: 0.9058587709753164
  - `pr_auc`: 0.338184524456533
  - `imputation_reference`: `healthy_median`
  - missing/skipped feature column 없음
- `reports/healthy_alert_windows.csv`
  - healthy alert window 736개
- `reports/tjs_anchor_ranked_windows.csv`
  - TJS anchor ranking 95개

현재 해석:

- Healthy reference가 8259개에서 14704개 window로 크게 늘었습니다.
- TJS anchor는 이번 단계에서 추가 수집하지 않았으므로 95개로 유지됩니다.
- ROC-AUC는 0.8964에서 0.9059로 상승했습니다.
- PR-AUC는 0.3430에서 0.3382로 소폭 하락했습니다. healthy window가 크게 늘어난 class imbalance 상황에서는 자연스러운 변화일 수 있습니다.
- healthy alert가 413개에서 736개로 늘었으므로, 다음에는 high-risk healthy false positive의 반복 선수/시기/role change를 검토하는 것이 좋습니다.

다음 권장 작업:

- TJS sample을 125개 또는 150개 이벤트까지 확장
- `reports/healthy_alert_windows.csv`를 pitcher별로 요약하는 false-positive diagnostic script 추가
- 2019 healthy/control을 월별 또는 전후반기로 나눠 score drift를 확인
- KBO-compatible reduced feature set 분리

## 추가 진행: TJS 150개 이벤트 확장과 false-positive 진단 스크립트 추가

날짜: 2026-07-09

사용자 요청에 따라 다음 권장 작업 두 가지를 모두 진행했습니다. TJS registry 상위 150개 이벤트까지 pre-surgery Statcast 수집을 확장했고, high-risk healthy false positive를 자동 요약하는 진단 스크립트를 추가했습니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02_collect_statcast_for_registry.py --config config\config.yaml --limit 150
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\05_run_mts.py --config config\config.yaml
.venv\Scripts\python.exe src\06_diagnose_alerts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

수집 중 특이사항:

- 기존 `TJS_00001`부터 `TJS_00100`까지는 대부분 cache hit로 재사용했습니다.
- `TJS_00101`부터 `TJS_00150`까지 새 raw parquet를 추가 저장했습니다.
- `TJS_00133` Jose Castillo와 `TJS_00146` Brock Stewart는 해당 구간 Statcast row가 없어 skip됐습니다.
- `TJS_00114` Seranthony Dominguez처럼 raw row가 매우 적은 이벤트는 parquet는 생성됐지만 valid 10-game anchor가 없을 수 있습니다.

현재 raw data 상태:

- `data/raw/statcast_pitchers/`
  - TJS event parquet file 총 146개
- `data/raw/statcast_league/`
  - league chunk parquet file 총 65개
  - 2019년 4~9월 control data 포함

재생성 결과:

- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 25140개
- `data/processed/window_features.csv`
  - 전체 window 18312개
  - healthy window 14728개
  - near-TJS excluded window 3445개
  - TJS anchor window 139개
- `data/processed/tjs_registry_with_anchors.csv`
  - valid TJS anchor 139개
- `data/processed/mts_scores.csv`
  - scored row 14867개
  - healthy 14728개
  - TJS 139개
- `reports/mts_summary.json`
  - `roc_auc`: 0.9032455187398154
  - `pr_auc`: 0.3620688065260551
  - `imputation_reference`: `healthy_median`
  - missing/skipped feature column 없음

추가한 진단 스크립트:

- `src/06_diagnose_alerts.py`
  - `data/processed/mts_scores.csv`를 읽어 alert diagnostics를 생성
  - healthy false-positive를 pitcher별/월별로 요약
  - TJS anchor capture summary를 별도 저장

새로 생성한 진단 파일:

- `reports/healthy_alert_pitcher_summary.csv`
  - healthy pitcher별 window 수, alert 수, alert rate, max/mean risk 요약
- `reports/healthy_alert_month_summary.csv`
  - 월별 healthy window 수, alert 수, alert rate 요약
- `reports/healthy_alert_top_windows.csv`
  - healthy alert window를 risk 내림차순으로 저장
- `reports/tjs_anchor_capture_summary.csv`
  - TJS anchor 139개를 risk 순위와 함께 저장
- `reports/alert_diagnostics.json`
  - 전체 alert 진단 요약

Alert diagnostics:

- healthy alert windows: 737 / 14728
- TJS alert windows: 104 / 139
- healthy alert rate: 0.0500
- TJS alert rate: 0.7482
- healthy pitchers with alert: 102 / 606

상위 반복 healthy alert pitcher:

- Chaz Roe: 53 alert windows / 59 healthy windows
- Hector Neris: 49 / 57
- Matt Barnes: 37 / 60
- Yusmeiro Petit: 37 / 70
- Adam Kolarek: 32 / 68
- Brad Hand: 32 / 49

현재 해석:

- TJS positive reference가 95개에서 139개 anchor로 늘었습니다.
- Healthy reference는 2019년 4~9월 control을 포함해 14728 window로 유지됩니다.
- ROC-AUC는 0.9059에서 0.9032로 거의 유지됐고, PR-AUC는 0.3382에서 0.3621로 상승했습니다.
- TJS alert capture는 104/139, 약 74.8%입니다.
- healthy alert는 threshold 정의상 약 5% 수준이며, 실제로 737/14728입니다.
- 반복 alert가 일부 reliever에게 집중되어 있어, 다음 단계에서는 role/pitch mix archetype이 TJS reference와 비슷해서 생기는 구조적 false positive인지 확인해야 합니다.

다음 권장 작업:

- `reports/healthy_alert_pitcher_summary.csv`의 상위 반복 alert pitcher를 수동 검토
- role별 starter/reliever 분리 또는 pitch count/appearance type 기준 diagnostic 추가
- TJS sample을 200개 이벤트까지 확장하기 전, 현재 139 anchor 기준으로 season/year confounding summary 추가
- KBO-compatible reduced feature set 분리

## 추가 진행: role proxy와 season/year confounding 진단 추가

날짜: 2026-07-09

TJS sample을 더 늘리기 전에 현재 139개 TJS anchor 기준으로 모델 신호가 role과 season에 따라 어떻게 달라지는지 진단했습니다. 새 데이터 다운로드는 하지 않았고, 기존 `data/processed/mts_scores.csv`를 기반으로 `src/06_diagnose_alerts.py`를 확장했습니다.

수정한 내용:

- `src/06_diagnose_alerts.py`
  - `role_proxy` column 추가
  - role proxy 기준:
    - `starter_like`: `pitch_count_mean_10 >= 60`
    - `relief_like`: `pitch_count_mean_10 <= 35`
    - `swing_mixed`: 그 사이
  - role별 healthy/TJS window 수, alert 수, risk 평균, ROC-AUC, PR-AUC 요약 추가
  - season별 healthy/TJS window 수, alert 수, risk 평균, ROC-AUC, PR-AUC 요약 추가
  - season x role proxy 교차 요약 추가
  - `alert_diagnostics.json`에 role/season 요약 포함

실행한 명령:

```powershell
.venv\Scripts\python.exe src\06_diagnose_alerts.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

새로 생성/갱신한 진단 파일:

- `reports/role_proxy_summary.csv`
- `reports/season_group_summary.csv`
- `reports/season_role_summary.csv`
- `reports/alert_diagnostics.json`

Role proxy summary:

- `relief_like`
  - 전체 11505 windows
  - healthy 11419, TJS 86
  - healthy alert rate 0.0542
  - TJS alert rate 0.7209
  - ROC-AUC 0.8955
  - PR-AUC 0.3426
- `starter_like`
  - 전체 2887 windows
  - healthy 2851, TJS 36
  - healthy alert rate 0.0284
  - TJS alert rate 0.6944
  - ROC-AUC 0.9033
  - PR-AUC 0.3167
- `swing_mixed`
  - 전체 475 windows
  - healthy 458, TJS 17
  - healthy alert rate 0.0808
  - TJS alert rate 1.0000
  - ROC-AUC 0.9883
  - PR-AUC 0.6753

Season summary 주요 관찰:

- 전체 score 기준:
  - ROC-AUC 0.9032
  - PR-AUC 0.3621
- 2019 season:
  - healthy 14643 windows
  - TJS 18 windows
  - ROC-AUC 0.8444
  - PR-AUC 0.0561
- 2020 season:
  - healthy 24 windows
  - TJS 26 windows
  - ROC-AUC 0.8494
  - PR-AUC 0.9101

현재 해석:

- reliever-like와 starter-like 모두에서 ROC-AUC가 약 0.90 수준으로 유지되어, 신호가 특정 role proxy 하나에만 의존한다고 보기는 어렵습니다.
- 다만 false positive는 reliever-like에 더 많이 몰립니다. healthy alert 737개 중 619개가 relief-like입니다.
- 2019년은 healthy control이 대부분이고 TJS anchor가 적어서 PR-AUC가 매우 낮게 나옵니다. 이는 season/year imbalance가 metric 해석에 큰 영향을 줄 수 있음을 보여줍니다.
- 2020년은 TJS anchor 비중이 상대적으로 커서 PR-AUC가 높게 나오지만, 표본 수가 작으므로 과해석하면 안 됩니다.
- 다음 단계는 모델 확장 전에 season-stratified evaluation을 더 엄격히 설계하거나, role별 reference/scoring을 따로 계산해보는 것입니다.

다음 권장 작업:

- role별로 separate healthy/TJS reference를 만든 MTS score와 current pooled-reference score를 비교
- 2019 healthy-heavy imbalance를 줄이기 위한 season-balanced sampling diagnostic 추가
- TJS sample을 200개까지 늘리기 전, 현재 결과를 기준으로 false positive 상위 reliever의 feature profile을 수동 점검

## 추가 진행: role-specific MTS와 season-balanced sampling 비교

날짜: 2026-07-09

이전 단계에서 권장한 두 가지 진단을 모두 추가했습니다. 기존 pooled-reference MTS 결과는 유지하고, 별도 스크립트에서 role별 separate-reference MTS와 season-balanced sampling diagnostic을 계산했습니다.

추가한 파일:

- `src/07_compare_mts_variants.py`

실행한 명령:

```powershell
.venv\Scripts\python.exe src\07_compare_mts_variants.py --config config\config.yaml
.venv\Scripts\python.exe -m compileall src tests
```

새로 생성한 report:

- `reports/role_specific_mts_scores.csv`
- `reports/role_specific_mts_summary.csv`
- `reports/season_balanced_sampling_iterations.csv`
- `reports/mts_variant_diagnostics.json`

Role-specific MTS 방식:

- 기존 pooled MTS와 달리 role proxy별로 healthy scaler/covariance와 TJS center를 따로 fit합니다.
- role proxy 기준은 이전 진단과 같습니다.
  - `starter_like`: `pitch_count_mean_10 >= 60`
  - `relief_like`: `pitch_count_mean_10 <= 35`
  - `swing_mixed`: 그 사이
- 각 role별 threshold는 해당 role healthy risk의 95 percentile로 잡았습니다.

Role-specific MTS 결과:

- `relief_like`
  - healthy 11419, TJS 86
  - ROC-AUC 0.9010
  - PR-AUC 0.3946
  - TJS alert 63/86 = 73.3%
- `starter_like`
  - healthy 2851, TJS 36
  - ROC-AUC 0.9083
  - PR-AUC 0.2992
  - TJS alert 26/36 = 72.2%
- `swing_mixed`
  - healthy 458, TJS 17
  - ROC-AUC 0.9870
  - PR-AUC 0.5956
  - TJS alert 17/17 = 100.0%

Pooled role-proxy diagnostic과 비교:

- pooled reference 기준 `relief_like` PR-AUC는 0.3426이었고, role-specific reference에서는 0.3946으로 개선됐습니다.
- pooled reference 기준 `starter_like` PR-AUC는 0.3167이었고, role-specific reference에서는 0.2992로 소폭 하락했습니다.
- pooled reference 기준 `swing_mixed` PR-AUC는 0.6753이었고, role-specific reference에서는 0.5956으로 하락했습니다.

현재 해석:

- reliever-like false positive가 많았던 문제에는 role-specific reference가 일부 도움이 될 수 있습니다.
- starter-like와 swing_mixed에서는 pooled reference가 더 낫거나 비슷합니다.
- 따라서 당장 전체 모델을 role-specific으로 바꾸기보다는, pooled score를 기본으로 두고 reliever-like에 대해 보조 진단 또는 별도 threshold를 검토하는 방향이 좋습니다.

Season-balanced sampling 방식:

- 기존 pooled MTS의 `risk_tjs`를 그대로 사용했습니다.
- healthy와 TJS가 모두 있는 season만 대상으로 했습니다.
- eligible seasons: 2014, 2015, 2016, 2017, 2018, 2019, 2020
- 2021은 TJS anchor만 있고 healthy window가 없어 제외됐습니다.
- 각 season에서 healthy window를 TJS window 수의 최대 5배까지만 downsample했습니다.
- 100회 반복 sampling을 수행했습니다.

Season-balanced pooled-score diagnostic 결과:

- 반복당 평균 healthy windows: 169
- 반복당 평균 TJS windows: 124
- mean ROC-AUC: 0.8529
- std ROC-AUC: 0.0061
- mean PR-AUC: 0.8643
- std PR-AUC: 0.0093

현재 해석:

- season-balanced sampling을 하면 ROC-AUC는 전체 pooled score의 0.9032보다 낮은 0.8529 수준으로 내려갑니다.
- 이는 전체 지표가 2019 healthy-heavy 구성의 영향을 받고 있음을 시사합니다.
- PR-AUC는 class balance가 훨씬 덜 불균형해지면서 0.8643으로 높게 나옵니다. 이 값은 운영 성능으로 해석하기보다는, balanced diagnostic에서 TJS window ranking이 꽤 유지된다는 신호로 봐야 합니다.
- 다음에는 season-balanced diagnostic을 threshold/alert capture 기준으로도 확장하거나, season-balanced reference 자체를 fit하는 실험을 할 수 있습니다.

다음 권장 작업:

- reliever-like에 대해 pooled threshold와 role-specific threshold의 false positive 차이를 선수 단위로 비교
- season-balanced reference fit 실험 추가
- KBO-compatible reduced feature set 정의

## 추가 진행: 2018년 holdout test data 생성

날짜: 2026-07-15

사용자 요청에 따라 기존 2019년 중심 control과 다른 연도의 test data를 만들기 위해 2018년 league-wide control 데이터를 추가 수집했습니다. 이번 목적은 메인 pooled 결과를 갱신하는 것이 아니라, 2018 season을 별도 holdout test set으로 떼어 cross-season test를 해보는 것입니다.

추가 실행한 명령:

```powershell
.venv\Scripts\python.exe src\02b_collect_statcast_league_chunks.py --config config\config.yaml --start 2018-04-01 --end 2018-09-30 --chunk-days 3
.venv\Scripts\python.exe src\03_build_pitcher_game_log.py --config config\config.yaml
.venv\Scripts\python.exe src\04_build_windows.py --config config\config.yaml
.venv\Scripts\python.exe src\08_build_holdout_test.py --config config\config.yaml --test-season 2018
.venv\Scripts\python.exe -m compileall src tests
```

수집/재생성 결과:

- `data/raw/statcast_league/`
  - 2018년 4~9월 league control parquet 61개 추가
- `data/interim/pitcher_game_log.csv`
  - pitcher-game row 45357개
- `data/processed/window_features.csv`
  - 전체 window 37073개
  - healthy window 33443개
  - exclude_tjs_nearby window 3490개
  - TJS anchor window 140개

season별 window 분포:

```text
season  healthy  tjs  exclude_tjs_nearby
2014         16    2                  469
2015          9   22                  497
2016          7   18                  422
2017          4   17                  592
2018      14673   21                  565
2019      18710   19                  566
2020         24   26                  299
2021          0   15                   80
```

추가한 파일:

- `src/08_build_holdout_test.py`

생성된 holdout test 산출물:

- `data/processed/holdout_2018_test_windows.csv`
  - 2018 test windows 14694개
- `data/processed/holdout_2018_mts_scores.csv`
  - 2018 holdout score 14694개
- `reports/holdout_2018_summary.json`

Holdout scoring 방식:

- test season: 2018
- train set: 2018을 제외한 healthy/TJS windows
- test set: 2018 healthy/TJS windows
- threshold: train healthy risk의 95 percentile
- 이 실험은 cross-season separation test이며, strict chronological prospective test는 아닙니다.

Holdout 결과:

- train healthy windows: 18770
- train TJS windows: 119
- test healthy windows: 14673
- test TJS windows: 21
- test ROC-AUC: 0.8615467995962782
- test PR-AUC: 0.14586371405989823
- test healthy alerts: 797 / 14673
- test TJS alerts: 15 / 21

현재 해석:

- 2018 holdout에서도 ROC-AUC 0.862로 TJS window가 healthy보다 높은 score를 받는 경향은 유지됩니다.
- PR-AUC는 0.146으로 기존 pooled result보다 낮습니다. 이는 다른 연도 test에서 risk 상위권에 healthy false positive가 더 섞인다는 뜻입니다.
- alert 기준으로 보면 train healthy 95 percentile threshold를 적용했을 때 2018 TJS anchor 21개 중 15개가 alert로 잡혔습니다.
- 즉, 다른 연도에서도 신호는 유지되지만, pooled retrospective result보다 약해집니다. 이 결과는 season/year generalization 검증이 중요하다는 점을 뒷받침합니다.

주의:

- `window_features.csv`는 2018 control 추가 후 최신화됐습니다.
- 이번 holdout 결과는 `holdout_2018_*` 파일을 기준으로 해석해야 합니다.
- 메인 `mts_scores.csv`와 `mts_summary.json`은 별도 pooled scoring 산출물이므로, 2018 control까지 포함한 메인 결과로 갱신하려면 `src/05_run_mts.py`를 다시 실행해야 합니다.

## 추가 진행: 특정 선수 MTS risk 리포트 스크립트 추가

날짜: 2026-07-20

팀원이 실제 선수 단위로 결과를 해석할 수 있도록 `src/09_report_player_risk.py`를 추가했습니다.

사용 예시:

```powershell
.venv\Scripts\python.exe src\09_report_player_risk.py --config config\config.yaml --player-name Sabathia --top-n 5
.venv\Scripts\python.exe src\09_report_player_risk.py --config config\config.yaml --mlbamid 282332 --top-n 5
```

스크립트는 `data/processed/mts_scores.csv`를 읽고 다음 정보를 출력합니다.

- 최신 10경기 window
- `D_H`: healthy reference와의 거리
- `D_T`: TJS pre-surgery reference와의 거리
- `risk_tjs`: TJS reference에 상대적으로 가까운 정도
- `alert`: 현재 기준선 초과 여부
- 해당 선수의 risk 상위 window 목록

조회 결과는 기본적으로 `reports/player_risk_<검색어>.csv`에도 저장됩니다.
