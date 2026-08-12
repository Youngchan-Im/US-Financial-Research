# U.S. Financial Research Project Data Dictionary

## 데이터셋

| 항목 | 내용 |
|---|---|
| 파일 | `data/macro_data.csv` |
| 관측 기간 | `2019-01-01`부터 `2024-12-31`까지 |
| 구조 | `date`와 다섯 FRED series를 가진 wide format |
| 병합 기준 | `date` 기준 `outer` 병합 |
| 날짜 의미 | FRED에 기록된 관측 날짜 |
| 결측치 | monthly와 daily frequency 차이, 주말·휴일, 자료 미제공 값 때문에 발생할 수 있음 |
| 수정 가능성 | 원자료 기관과 FRED 갱신에 따라 과거 값이 수정될 수 있음 |

## 공통 해석 기준

- percent 단위 지표의 수준 차이는 퍼센트포인트로 기록한다.
- `CPIAUCSL`은 물가상승률이 아니라 가격 지수 수준이다.
- CPI 전년 동월 대비 상승률은 월별 관측값만 남긴 뒤 `pct_change(12) × 100`으로 계산한다.
- monthly와 daily series를 같은 row 수로 해석하지 않는다.
- 결측치를 자동으로 `0`이나 앞의 값으로 채우지 않는다.
- 단위가 다른 지표를 하나의 y축에서 값의 크기로 직접 비교하지 않는다.
- 함께 움직인 지표가 있어도 인과관계로 단정하지 않는다.

## column 사전

| column | 자료형 | 의미 |
|---|---|---|
| `date` | datetime | FRED 관측 날짜 |
| `UNRATE` | numeric | 미국 실업률, percent, monthly |
| `FEDFUNDS` | numeric | 연방기금실효금리 월평균, percent, monthly |
| `CPIAUCSL` | numeric | 도시 소비자물가지수 수준, index 1982-1984=100, monthly |
| `DGS10` | numeric | 10년 만기 미국 국채 constant maturity 시장 수익률, percent, daily |
| `T10Y2Y` | numeric | 10년물 금리에서 2년물 금리를 뺀 spread, percent, daily |

## 관측 요약

| series ID | 유효 관측 수 | 시작일 | 종료일 | 시작값 | 종료값 | 최솟값 | 최댓값 |
|---|---:|---|---|---:|---:|---:|---:|
| `UNRATE` | 72 | 2019-01-01 | 2024-12-01 | 4 | 4.1 | 3.4 | 14.8 |
| `FEDFUNDS` | 72 | 2019-01-01 | 2024-12-01 | 2.4 | 4.48 | 0.05 | 5.33 |
| `CPIAUCSL` | 72 | 2019-01-01 | 2024-12-01 | 252.561 | 317.604 | 252.561 | 317.604 |
| `DGS10` | 1501 | 2019-01-02 | 2024-12-31 | 2.66 | 4.58 | 0.52 | 4.98 |
| `T10Y2Y` | 1501 | 2019-01-02 | 2024-12-31 | 0.16 | 0.33 | -1.08 | 1.59 |

## 지표 사전

### UNRATE

| 항목 | 내용 |
|---|---|
| series ID | `UNRATE` |
| 이름 | Unemployment Rate |
| source | U.S. Bureau of Labor Statistics |
| unit | Percent |
| frequency | Monthly |
| seasonal adjustment | Seasonally Adjusted |
| 값의 의미 | 실업자 수가 노동력에서 차지하는 비율 |
| 변화 읽기 | 두 실업률 수준의 차이는 퍼센트포인트로 기록 |
| 결측치 기준 | 월별 관측이므로 일별 row에는 값이 없음 |
| 한계 | 그래프만으로 실업률 변화의 원인을 단정하지 않음 |
| 공식 페이지 | <https://fred.stlouisfed.org/series/UNRATE> |

### FEDFUNDS

| 항목 | 내용 |
|---|---|
| series ID | `FEDFUNDS` |
| 이름 | Federal Funds Effective Rate |
| source | Board of Governors of the Federal Reserve System (US) |
| unit | Percent |
| frequency | Monthly |
| seasonal adjustment | Not Seasonally Adjusted |
| 값의 의미 | 일별 연방기금실효금리의 월평균 |
| 변화 읽기 | 금리 수준의 차이는 퍼센트포인트로 기록 |
| 결측치 기준 | 월별 관측이므로 일별 row에는 값이 없음 |
| 한계 | 연방공개시장위원회(FOMC) 목표 범위 자체와 동일한 series로 해석하지 않음 |
| 공식 페이지 | <https://fred.stlouisfed.org/series/FEDFUNDS> |

### CPIAUCSL

| 항목 | 내용 |
|---|---|
| series ID | `CPIAUCSL` |
| 이름 | Consumer Price Index for All Urban Consumers: All Items in U.S. City Average |
| source | U.S. Bureau of Labor Statistics |
| unit | Index 1982-1984=100 |
| frequency | Monthly |
| seasonal adjustment | Seasonally Adjusted |
| 값의 의미 | 도시 소비자 상품·서비스 바구니의 가격 지수 수준 |
| 변화 읽기 | 물가상승률은 지수의 percent change로 별도 계산 |
| 결측치 기준 | 월별 관측이므로 일별 row에는 값이 없음 |
| 한계 | 지수 수준을 물가상승률 percent로 읽지 않음 |
| 공식 페이지 | <https://fred.stlouisfed.org/series/CPIAUCSL> |

### DGS10

| 항목 | 내용 |
|---|---|
| series ID | `DGS10` |
| 이름 | Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis |
| source | Board of Governors of the Federal Reserve System (US) |
| unit | Percent |
| frequency | Daily |
| seasonal adjustment | Not Seasonally Adjusted |
| 값의 의미 | 10년 만기 constant maturity 기준 미국 국채 시장 수익률 |
| 변화 읽기 | 금리 수준의 차이는 퍼센트포인트로 기록 |
| 결측치 기준 | 주말, 휴일, 자료 미제공일에 값이 없을 수 있음 |
| 한계 | 특정 채권의 가격, 쿠폰, 실현수익률과 동일하게 읽지 않음 |
| 공식 페이지 | <https://fred.stlouisfed.org/series/DGS10> |

### T10Y2Y

| 항목 | 내용 |
|---|---|
| series ID | `T10Y2Y` |
| 이름 | 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity |
| source | Federal Reserve Bank of St. Louis |
| unit | Percent |
| frequency | Daily |
| seasonal adjustment | Not Seasonally Adjusted |
| 값의 의미 | 10년물 금리에서 2년물 금리를 뺀 spread |
| 변화 읽기 | 0보다 작으면 10년물 금리가 2년물보다 낮은 상태 |
| 결측치 기준 | 주말, 휴일, 기초 금리 자료 미제공일에 값이 없을 수 있음 |
| 한계 | 음수 값만으로 경기침체의 발생 여부나 시점을 확정하지 않음 |
| 공식 페이지 | <https://fred.stlouisfed.org/series/T10Y2Y> |

## 그래프 해석 메모

- `UNRATE`: 2019-01-01부터 2024-12-01까지 4%에서 4.1%로 0.1 퍼센트포인트 상승했다. 그래프만으로 변화 원인을 단정하지 않는다.
- `FEDFUNDS`: 2019-01-01부터 2024-12-01까지 2.4%에서 4.48%로 2.08 퍼센트포인트 상승했다. 이 series를 연방공개시장위원회(FOMC) 목표 범위 자체로 읽지 않는다.
- `CPIAUCSL`: 지수 수준은 252.561에서 317.604로 변했다. 2024-12-01의 전년 동월 대비 변화율은 2.871%다. 지수 수준과 물가상승률을 같은 값으로 읽지 않는다.
- `DGS10`: 관측 기간의 값은 0.52%부터 4.98% 범위에 있었다. 일별 변동의 원인은 이 그래프만으로 단정하지 않는다.
- `T10Y2Y`: 관측 기간의 spread는 -1.08부터 1.59 퍼센트포인트 범위에 있었고, 음수 관측일은 544개로 전체 유효 관측일의 36.24%였다. 음수 값만으로 경기침체의 발생 여부나 시점을 확정하지 않는다.

## 시각화

- 파일: `assets/macro_charts.png`
- 구성: 다섯 series를 각각의 y축에 표시
- 기간: `2019-01-01`부터 `2024-12-31`까지
- `T10Y2Y` 패널: spread `0` 기준선 포함
- 주의: 패널별 y축 단위와 범위가 다르므로 선의 높이를 패널 사이에서 직접 비교하지 않음
