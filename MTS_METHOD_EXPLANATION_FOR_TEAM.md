# MLB 투수 Tommy John Surgery 위험 신호 탐지를 위한 MTS 기반 접근

## 초록

이 문서는 MLB 투수의 Tommy John Surgery(TJS, 팔꿈치 인대 재건 수술) 직전 경기 패턴을 탐지하기 위해 현재 프로젝트에서 만든 거리 기반 모델을 설명한다. 이 모델은 일반적인 AI classifier처럼 "이 선수가 수술을 받을 것이다/아니다"를 직접 맞히는 모델이 아니다. 대신 각 투수의 최근 10경기 패턴이 건강한 투수들의 일반적인 패턴에 가까운지, 아니면 실제 TJS 수술 전 투수들의 패턴에 가까운지를 비교한다.

현재 모델은 Mahalanobis distance를 이용한 dual-reference MTS 방식이다. 쉽게 말하면, 두 개의 기준점을 만든다. 하나는 healthy reference이고, 다른 하나는 TJS pre-surgery reference이다. 어떤 투수의 최근 10경기 데이터를 이 두 기준점과 비교해, TJS 직전 패턴에 상대적으로 더 가까우면 `Risk_TJS` 점수가 높아진다.

현재까지 MLB 데이터로 end-to-end 파이프라인이 정상 작동했고, 중간 규모 데이터에서 TJS 수술 전 window와 healthy window를 어느 정도 구분하는 신호를 확인했다. 다만 이 모델은 아직 의료적 예측 모델이 아니라 연구용 위험 신호 탐지 모델이다.

## 먼저 보는 핵심 용어

이 문서를 읽을 때 자주 나오는 용어를 먼저 간단히 정리하면 다음과 같다.

```text
window:
한 투수의 최근 10경기를 묶은 분석 단위

healthy window:
TJS 수술 근처가 아닌 일반 투수/일반 시점의 window

TJS window:
실제 TJS 수술 전 마지막 MLB 등판으로 끝나는 최근 10경기 window

reference:
비교 기준이 되는 대표 패턴

healthy reference:
건강한 투수 window들의 대표 패턴

TJS reference:
TJS 수술 전 window들의 대표 패턴

Risk_TJS:
어떤 window가 healthy reference보다 TJS reference에 얼마나 가까운지 나타내는 점수

alert:
Risk_TJS가 기준값보다 높아서 "검토 필요"로 표시된 window

false positive:
실제 label은 healthy인데 alert가 뜬 window
```

이 모델을 가장 짧게 설명하면 다음과 같다.

```text
최근 10경기 패턴을 보고,
healthy reference에 가까운지 TJS reference에 가까운지 비교한다.
TJS reference에 더 가까우면 Risk_TJS가 높아지고,
Risk_TJS가 기준선보다 높으면 alert로 표시한다.
```

## 1. 연구 배경

Tommy John Surgery는 투수에게 매우 큰 영향을 주는 팔꿈치 수술이다. 수술이 발생한 뒤에는 이미 부상이 현실화된 상태이므로, 스포츠 데이터 분석 관점에서는 수술 전에 어떤 변화가 있었는지 살펴보는 것이 중요하다.

하지만 이 프로젝트의 목표는 당장 "누가 수술을 받을지"를 예측하는 완성형 AI를 만드는 것이 아니다. 지금 단계의 목표는 더 조심스럽다.

```text
TJS 수술을 받은 투수들의 수술 전 경기 패턴이
일반적인 healthy 투수들의 경기 패턴과 다르게 보이는가?
```

이 질문에 먼저 답해야 한다. 만약 MLB 데이터에서 그런 신호가 확인된다면, 이후 KBO에 적용 가능한 축소 모델을 만드는 근거가 생긴다.

## 2. 왜 classifier가 아닌가?

많은 AI 모델은 classifier 형태로 만들어진다. classifier는 보통 다음 질문에 답한다.

```text
이 투수는 TJS를 받을 것인가?
예 / 아니오
```

하지만 이번 프로젝트에서는 classifier를 바로 만들지 않았다. 이유는 세 가지다.

첫째, TJS는 매우 드문 사건이다. 대부분의 투수 window는 TJS가 아니고, TJS 직전 window는 매우 적다. 이런 상황에서는 classifier가 데이터 불균형에 쉽게 흔들릴 수 있다.

둘째, 현재 단계에서는 "예측"보다 "패턴 검증"이 더 중요하다. 우리는 먼저 실제 수술 전 패턴이 healthy 패턴과 얼마나 다른지 확인해야 한다.

셋째, KBO 적용을 염두에 두면 설명 가능성이 중요하다. distance-based score는 "어느 기준에 더 가까운가"라는 방식으로 설명하기 쉽다.

따라서 현재 모델은 다음과 같은 질문에 답한다.

```text
최근 10경기 패턴이 healthy reference보다
TJS pre-surgery reference에 더 가까운가?
```

## 3. 데이터 구성

현재 파이프라인은 다음 순서로 구성되어 있다.

```text
1. 공개 TJS registry에서 MLB 투수 수술자 명단 수집
2. MLBAM ID가 있는 MLB 투수만 필터링
3. pybaseball / Statcast로 pitch-level data 수집
4. pitch-level data를 pitcher-game log로 집계
5. 투수별 최근 10경기 rolling window 생성
6. TJS reference와 healthy reference 생성
7. dual-reference MTS score 계산
8. 결과 CSV와 진단 리포트 생성
```

현재 주요 데이터 규모는 다음과 같다.

```text
TJS raw parquet 파일: 146개
league control parquet 파일: 65개
pitcher-game log: 25,140 rows
전체 window: 18,312개
healthy window: 14,728개
TJS 수술 전 window: 139개
scored rows: 14,867개
```

## 4. 중요한 label 규칙

이 프로젝트에서 가장 중요한 방법론 규칙은 다음이다.

```text
TJ Surgery Date는 label 확정용으로만 사용한다.
positive window의 anchor는 수술일이 아니라,
수술일 이전 마지막 MLB 등판일이다.
```

즉, 어떤 선수가 2020년 5월 1일에 TJS를 받았다고 해도, 2020년 5월 1일 자체를 경기 window의 끝으로 쓰지 않는다. 실제 경기 데이터에서 수술 전 마지막 MLB 등판일을 찾고, 그 등판으로 끝나는 최근 10경기를 TJS positive window로 사용한다.

이 규칙이 중요한 이유는 간단하다. 수술일은 경기일이 아니다. 수술은 진단과 결정 이후에 이뤄지는 이벤트다. 따라서 수술일을 직접 anchor로 쓰면 실제 경기 패턴보다 사후 정보가 섞일 위험이 있다.

## 5. Window와 Feature

모델의 기본 분석 단위는 투수의 최근 10경기 window이다.

예를 들어 어떤 투수가 4월 1일부터 5월 20일까지 여러 경기에 등판했다면, 각 시점마다 최근 10경기를 묶어 하나의 window vector를 만든다.

현재 MLB-full feature에는 다음과 같은 정보가 포함된다.

```text
투구 수
상대한 타자 수
등판 간 휴식일
평균 구속
구속 변화 추세
회전수
릴리스 익스텐션
릴리스 포인트 변동성
무브먼트
zone rate
whiff rate
called strike rate
볼넷/삼진/홈런 rate
구종 비율
```

중요한 점은 현재 feature set이 MLB Statcast 기준이라는 것이다. KBO에서 그대로 얻기 어려운 feature도 포함되어 있다. 따라서 KBO 적용 단계에서는 KBO-compatible reduced feature set을 따로 정의해야 한다.

## 6. Healthy Reference와 TJS Reference

이 모델은 두 개의 reference를 사용한다.

첫 번째는 healthy reference이다. 이는 일반 MLB 투수들의 window 중 TJS 수술 근처가 아닌 window들로 구성된다. 현재는 2019년 4월부터 9월까지의 league-wide Statcast control data가 주요 healthy reference를 이룬다.

두 번째는 TJS pre-surgery reference이다. 이는 실제 TJS 수술을 받은 투수들에 대해, 수술 전 마지막 MLB 등판으로 끝나는 최근 10경기 window들이다.

두 reference는 다음처럼 해석할 수 있다.

```text
healthy reference:
일반적인 건강한 투수 window의 중심 패턴

TJS reference:
실제 TJS 수술 전 투수 window의 중심 패턴
```

## 7. MTS와 Mahalanobis Distance

현재 모델은 Mahalanobis distance를 사용한다. 일반적인 거리 계산은 단순히 두 점이 얼마나 떨어져 있는지를 본다. 하지만 야구 feature들은 서로 관련이 있다.

예를 들어 투구 수, 상대 타자 수, 휴식일, 구속 변화는 완전히 독립적이지 않을 수 있다. Mahalanobis distance는 이런 feature 간 상관 구조를 고려해서 거리를 계산한다.

일반적인 거리 계산을 비유하면 "직선거리"에 가깝다. 반면 Mahalanobis distance는 "이 데이터 세계에서 얼마나 특이한 방향으로 멀어졌는가"를 본다.

예를 들어 투구 수가 늘면 상대 타자 수가 같이 늘어나는 것은 자연스러운 변화일 수 있다. 이런 경우 두 feature가 같이 움직였다고 해서 무조건 이상하다고 보면 안 된다. Mahalanobis distance는 이런 자연스러운 동반 변화를 덜 이상하게 보고, 평소 같이 움직이지 않던 조합이 튀는 경우를 더 특이하게 본다.

이 프로젝트에서는 다음 두 거리를 계산한다.

```text
D_H(x) = 어떤 window x가 healthy reference에서 얼마나 먼가
D_T(x) = 어떤 window x가 TJS reference에서 얼마나 먼가
```

그리고 최종 위험 점수는 다음처럼 계산한다.

```text
Risk_TJS(x) = log((D_H(x) + epsilon) / (D_T(x) + epsilon))
```

해석은 다음과 같다.

```text
Risk_TJS가 높다:
healthy reference보다 TJS reference에 더 가깝다.

Risk_TJS가 낮다:
TJS reference보다 healthy reference에 더 가깝다.
```

여기서 epsilon은 0으로 나누는 문제를 막기 위한 아주 작은 값이다.

가장 중요한 해석은 다음 한 줄이다.

```text
D_H보다 D_T가 작으면,
즉 healthy보다 TJS reference에 더 가까우면,
Risk_TJS는 커진다.
```

## 8. 왜 dual-reference인가?

단일 reference 모델이라면 healthy 기준에서 얼마나 벗어났는지만 볼 수 있다.

하지만 어떤 투수가 healthy reference에서 멀다고 해서 반드시 TJS 직전 패턴과 가깝다는 뜻은 아니다. 단순히 특이한 투수일 수도 있고, role이 다를 수도 있고, 구종 스타일이 다를 수도 있다.

그래서 이 프로젝트는 healthy reference와 TJS reference를 동시에 둔다.

```text
healthy에서 멀기만 한가?
아니면 healthy에서 멀면서 동시에 TJS reference에 가까운가?
```

이 차이가 중요하다. 모델은 "이상함" 자체가 아니라 "TJS 직전 reference에 가까운 이상함"을 찾으려 한다.

## 9. Covariance 추정 방식

현재 구현에서 covariance는 healthy reference에서만 추정한다. TJS reference의 covariance를 따로 추정하지 않는다.

여기서 covariance는 feature들 사이의 관계를 나타내는 표라고 보면 된다. 예를 들어 투구 수와 상대 타자 수는 같이 움직일 가능성이 높다. 구속, 회전수, 릴리스 포인트도 서로 완전히 독립적이지 않을 수 있다.

이 covariance는 reference center를 만드는 데만 쓰는 것이 아니다. 실제로는 `D_H`와 `D_T`를 계산할 때, 즉 Mahalanobis distance를 계산할 때 사용된다.

```text
distance = sqrt((x - center)^T * inverse_covariance * (x - center))
```

위 식에서 `inverse_covariance`가 healthy reference에서 추정한 covariance의 역행렬이다. 쉽게 말하면, covariance는 이 모델이 "어떤 방향의 차이는 자연스럽고, 어떤 방향의 차이는 특이한가"를 판단하는 거리 기준이다.

이유는 TJS window 수가 healthy window보다 훨씬 적기 때문이다. TJS sample이 적은 상태에서 TJS covariance를 따로 추정하면 불안정한 거리 계산이 될 수 있다.

현재 방식은 다음과 같다.

```text
1. healthy reference로 feature scaling 학습
2. healthy reference로 shrinkage covariance 학습
3. healthy center와 TJS center를 각각 계산
4. 동일한 healthy covariance 기준으로 D_H와 D_T 계산
```

기본 covariance estimator는 OAS shrinkage covariance이다.

OAS는 `Oracle Approximating Shrinkage`의 약자다. 이름은 어렵지만 아이디어는 단순하다.

```text
데이터에서 계산한 covariance를 그대로 믿으면 흔들릴 수 있으니,
조금 더 안정적인 형태로 보정해서 사용한다.
```

feature가 많거나 sample이 충분히 크지 않을 때, 일반 covariance는 불안정할 수 있다. 그러면 Mahalanobis distance도 흔들린다. OAS shrinkage covariance는 데이터에서 feature 간 관계를 배우되, 너무 튀는 추정을 줄여서 더 안정적인 covariance를 만든다.

비유하면 다음과 같다.

```text
raw covariance:
데이터가 말하는 관계를 그대로 믿음

OAS shrinkage covariance:
데이터가 말하는 관계를 듣되,
표본이 작아서 생긴 과한 흔들림은 줄임
```

따라서 현재 모델에서 OAS는 `D_H`와 `D_T`를 더 안정적으로 계산하기 위한 안전장치다.

## 10. 현재 결과

현재 pooled-reference MTS의 주요 결과는 다음과 같다.

```text
healthy windows: 14,728개
TJS windows: 139개
ROC-AUC: 0.903
PR-AUC: 0.362
```

ROC-AUC는 모델의 전반적인 순위 구분 능력을 나타낸다. 쉽게 말하면, TJS window 하나와 healthy window 하나를 랜덤으로 뽑았을 때 모델이 TJS window에 더 높은 `Risk_TJS`를 줄 확률에 가깝다.

```text
ROC-AUC 0.903:
TJS window와 healthy window를 하나씩 비교했을 때,
약 90.3% 정도는 TJS window가 더 높은 Risk_TJS를 받는다는 뜻
```

PR-AUC는 risk 상위권에 실제 TJS window가 얼마나 잘 모이는지를 보는 지표다. TJS처럼 드문 사건에서는 PR-AUC가 특히 중요하다.

```text
PR-AUC 0.362:
Risk_TJS가 높은 window들을 alert 후보로 볼 때,
그 상위권 안에 실제 TJS window가 랜덤보다 훨씬 많이 들어온다는 뜻
```

현재 TJS window 비율은 약 0.94%이다.

```text
TJS window: 139
전체 scored window: 14,867
TJS 비율: 약 0.94%
```

랜덤으로 window를 고르면 TJS가 나올 확률은 약 0.94%밖에 되지 않는다. 그런데 PR-AUC가 0.362라는 것은, risk ranking이 랜덤보다 훨씬 강한 신호를 가지고 있다는 뜻이다. 다만 PR-AUC가 1.0에 가까운 것은 아니므로, 아직 완성형 경고 모델로 해석하면 안 된다.

TJS alert capture는 다음과 같다.

```text
TJS alert windows: 104 / 139 = 74.8%
healthy alert windows: 737 / 14,728 = 5.0%
```

즉, healthy window 중 상위 약 5%를 alert로 잡았을 때, TJS 수술 전 anchor window의 약 75%가 alert에 포함된다.

여기서 alert는 실제 부상 확정이 아니다. alert는 단지 `Risk_TJS`가 기준값보다 높다는 표시다.

현재 기준값은 다음처럼 잡았다.

```text
healthy window들의 Risk_TJS 분포에서 95 percentile
```

즉, healthy 기준으로도 위험 점수가 높은 상위 5%를 alert로 표시한다.

```text
Risk_TJS >= healthy Risk_TJS의 95 percentile
이면 alert = True
```

가장 쉬운 비유는 다음과 같다.

```text
Risk_TJS = 온도계 숫자
alert = 온도가 기준선 이상이면 켜지는 경고등
```

따라서 정확한 해석은 다음이다.

```text
alert가 떴다 =
이 window가 TJS pre-surgery reference와 상대적으로 비슷해서
검토할 필요가 있다
```

반대로 잘못된 해석은 다음이다.

```text
alert가 떴다 =
이 투수는 TJS를 받을 것이다
```

다만 이 수치는 최종 예측 성능으로 해석하면 안 된다. 현재는 연구용 retrospective analysis이며, 미래 시점 예측 검증이나 season holdout 검증은 아직 충분하지 않다.
