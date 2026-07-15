# MLB 투수 Tommy John Surgery 위험 신호 분석 진행상황 공유

작성일: 2026-07-09

## 한 줄 요약

Tommy John Surgery(TJS, 팔꿈치 인대 수술)를 받은 MLB 투수들의 수술 전 경기 패턴을 Statcast 데이터로 분석하는 파이프라인을 만들었고, 현재는 중간 규모 prototype 모델까지 정상 실행되는 상태입니다.

## 이 프로젝트가 하려는 일

이 프로젝트의 목적은 투수가 Tommy John Surgery를 받기 전, 경기 데이터에서 평소와 다른 위험 신호가 나타나는지 탐색하는 것입니다.

중요한 점은 이것이 아직 “수술을 예측하는 완성된 AI 모델”은 아니라는 것입니다. 현재는 다음 질문에 답하는 탐색 모델입니다.

```text
이 투수의 최근 10경기 패턴이
건강한 투수들의 패턴에 더 가까운가,
아니면 TJS 수술 전 투수들의 패턴에 더 가까운가?
```

모델은 각 투수의 최근 10경기 데이터를 보고 `Risk_TJS`라는 거리 기반 점수를 계산합니다. 점수가 높을수록 TJS 수술 전 패턴에 더 가까운 것으로 해석합니다.

## 지금까지 완료한 것

1. TJS 수술자 명단 정리

공개 Google Sheet인 “Tommy John Surgery List”를 사용해 MLB 투수 수술자 명단을 정리했습니다. 선수 이름, 수술일, 팀, 나이, MLBAM ID 등을 정리했고, 분석에 필요한 형태로 저장했습니다.

2. Statcast 데이터 수집

MLBAM ID를 이용해 MLB Statcast 데이터를 수집했습니다. 먼저 작은 샘플로 테스트한 뒤 점진적으로 확장했습니다.

현재까지 수집한 데이터:

```text
TJS 투수 raw 데이터 파일: 146개
일반 MLB 경기 control 데이터 파일: 65개
```

3. 경기 단위 데이터로 변환

Statcast 원본은 투구 1개 단위 데이터입니다. 이를 투수의 경기 1개 단위로 요약했습니다.

예를 들어 한 경기마다 다음과 같은 정보를 만들었습니다.

- 총 투구 수
- 평균 구속
- 구속 변화
- 회전수
- 릴리스 포인트
- 헛스윙 비율
- 스트라이크 비율
- 구종 비율
- 등판 간 휴식일

현재 생성된 경기 단위 데이터:

```text
투수-경기 row: 25,140개
```

4. 최근 10경기 window 생성

각 투수에 대해 최근 10경기씩 묶은 분석 단위를 만들었습니다.

TJS 수술자에 대해서는 수술일 자체를 기준으로 삼지 않았습니다. 대신 “수술 전 마지막 MLB 등판일”을 찾고, 그 등판을 끝으로 하는 직전 10경기를 TJS 전조 window로 만들었습니다.

현재 생성된 window:

```text
전체 window: 18,312개
healthy window: 14,728개
TJS 수술 전 window: 139개
분석에서 제외한 수술 근처 window: 3,445개
```

5. 위험 점수 계산 모델 실행

모델이 정상적으로 끝까지 실행되었고, 각 window별 위험 점수를 생성했습니다.

최종 score 파일:

```text
data/processed/mts_scores.csv
```

요약 결과 파일:

```text
reports/mts_summary.json
```

## 현재 검증 결과

현재까지의 중간 검증 결과는 다음과 같습니다.

```text
분석된 전체 scoring row: 14,867개
healthy window: 14,728개
TJS window: 139개
ROC-AUC: 0.903
PR-AUC: 0.362
```

쉽게 말하면, 모델이 healthy window와 TJS 수술 전 window를 어느 정도 구분하는 신호를 잡고 있다는 뜻입니다.

특히 위험 점수가 높은 상위 목록에 실제 TJS 수술 전 window가 여러 개 포함되었습니다. 즉, “TJS 수술 전 패턴이 healthy 패턴과 다르게 보이는가?”라는 질문에 대해 현재까지는 긍정적인 신호가 있습니다.

## 추가 진단 결과

현재 모델이 특정 투수 역할군에만 의존하는지 보기 위해, 최근 10경기 평균 투구 수로 간단한 role proxy를 만들었습니다.

```text
starter_like: 최근 10경기 평균 투구 수 60개 이상
relief_like: 최근 10경기 평균 투구 수 35개 이하
swing_mixed: 그 사이
```

결과는 다음과 같습니다.

```text
relief_like ROC-AUC: 0.896, PR-AUC: 0.343
starter_like ROC-AUC: 0.903, PR-AUC: 0.317
swing_mixed ROC-AUC: 0.988, PR-AUC: 0.675
```

현재 신호는 reliever-like와 starter-like 양쪽에서 모두 어느 정도 유지됩니다. 다만 healthy false positive는 reliever-like window에 많이 몰립니다.

또한 season별 imbalance도 확인했습니다. 2019년 healthy control이 대부분이고 TJS anchor는 상대적으로 적기 때문에, 단순 전체 지표만 보면 연도 구성의 영향을 받을 수 있습니다.

추가로 role별 reference를 따로 잡는 실험도 했습니다. 즉, starter-like, relief-like, swing_mixed 각각에서 healthy 기준선과 TJS 기준선을 따로 만들고 다시 MTS score를 계산했습니다.

```text
role-specific relief_like PR-AUC: 0.395
role-specific starter_like PR-AUC: 0.299
role-specific swing_mixed PR-AUC: 0.596
```

reliever-like에서는 role-specific reference가 도움이 되었지만, starter-like와 swing_mixed에서는 pooled reference가 더 낫거나 비슷했습니다. 따라서 현재는 전체 모델을 role-specific으로 바로 바꾸기보다, pooled score를 기본으로 두고 reliever-like에 별도 보조 진단을 붙이는 방향이 좋아 보입니다.

season-balanced sampling도 수행했습니다. healthy와 TJS가 모두 있는 season만 대상으로 healthy window를 downsample해 100회 반복 평가했습니다.

```text
season-balanced mean ROC-AUC: 0.853
season-balanced mean PR-AUC: 0.864
```

이 결과는 전체 ROC-AUC 0.903보다 낮기 때문에, 전체 지표가 season 구성의 영향을 받는다는 점을 보여줍니다. 반대로 balanced setting에서도 TJS window ranking은 꽤 유지됩니다.

## 다만 아직 조심해야 하는 점

현재 결과는 유망하지만, 아직 최종 결론으로 보면 안 됩니다.

이유는 다음과 같습니다.

1. Healthy 기준 데이터가 아직 제한적입니다.

현재 healthy/control 데이터는 2019년 4월부터 9월까지 약 6개월치입니다. 이전보다 훨씬 넓어졌지만, 더 안정적인 기준선을 만들려면 여러 시즌의 일반 투수 데이터를 추가해야 합니다.

2. TJS sample도 더 늘려야 합니다.

현재 TJS 수술 전 window는 139개입니다. 더 많은 수술자 이벤트를 수집하면 결과가 더 안정됩니다.

3. 연도 차이의 영향이 있을 수 있습니다.

TJS 수술 전 데이터는 2015~2019년대 이벤트가 섞여 있고, healthy control은 현재 2019년 데이터 중심입니다. 따라서 일부 차이는 부상 신호가 아니라 시즌/환경 차이일 수도 있습니다.

4. 아직 의료적 예측 모델이 아닙니다.

현재 모델은 “위험 신호 탐색용 점수”입니다. 선수의 실제 부상 가능성을 직접 예측하거나 의학적 판단을 내리는 모델은 아닙니다.

## 현재 상태를 한 문장으로 표현하면

```text
데이터 수집부터 위험 점수 계산까지 end-to-end 파이프라인은 정상 작동했고,
중간 규모 데이터에서도 TJS 수술 전 패턴을 어느 정도 구분하는 신호를 확인했다.
```

## 다음 단계 제안

1. Healthy/control 데이터 확장

2019년 4~9월 control 데이터까지 확장했습니다. 다음에는 여러 시즌의 control 데이터를 추가하거나, 현재 2019년 control 안에서 월별 drift를 확인합니다.

2. TJS sample 확장

현재 상위 150개 이벤트까지 수집했으므로, 다음에는 바로 더 늘리기보다 현재 sample에서 false positive와 연도 차이를 먼저 점검하는 것이 좋습니다.

3. 연도별 검증 추가

특정 연도의 데이터만 보고 착시가 생기지 않도록 season별로 나누어 검증합니다.

4. False positive 검토

위험 점수가 높게 나온 healthy window들을 따로 모아 실제로 어떤 선수/경기인지 확인합니다.

현재 별도 검토 파일을 생성했습니다.

```text
reports/healthy_alert_windows.csv
reports/tjs_anchor_ranked_windows.csv
reports/healthy_alert_pitcher_summary.csv
reports/healthy_alert_month_summary.csv
reports/alert_diagnostics.json
reports/role_proxy_summary.csv
reports/season_group_summary.csv
reports/season_role_summary.csv
reports/role_specific_mts_summary.csv
reports/season_balanced_sampling_iterations.csv
reports/mts_variant_diagnostics.json
```

5. KBO 적용 가능 feature set 분리

MLB Statcast에서만 가능한 feature와 KBO에서도 쓸 수 있는 feature를 분리해, 추후 KBO-compatible version을 따로 테스트합니다.

## 공유용 결론

현재 단계에서는 “아이디어 검증”과 “파이프라인 구축”은 성공적으로 진행되었습니다.  
아직 최종 모델은 아니지만, TJS 수술 전 경기 패턴이 일반 healthy 패턴과 다르게 나타날 가능성을 확인했기 때문에 다음 단계로 확장할 가치가 있습니다.
