# U.S. Financial Research Project 기업 목록

## 수집 대상

| ticker | company_name | CIK | 프로젝트 분류 | 회계연도 종료 기준 | revenue concept 우선순위 |
|---|---|---|---|---|---|
| `AAPL` | Apple Inc. | `0000320193` | Technology | 9월 말 | `RevenueFromContractWithCustomerExcludingAssessedTax` -> `Revenues` |
| `MSFT` | Microsoft Corporation | `000078019` | Technology | 6월 30일 | `RevenueFromContractWithCustomerExcludingAssessedTax` -> `Revenues` |
| `JPM` | JPMorgan Chase & Co. | `000019617` | Banking | 12월 31일 | `Revenues` -> `RevenueFromContractWithCustomerExcludingAssessedTax` |
| `TSLA` | Tesla, Inc. | `0001318605` | Automotive and Energy | 12월 31일 | `RevenueFromContractWithCustomerExcludingAssessedTax` -> `Revenues` |
| `WMT` | Walmart Inc. | `0000104169` | Retail | 1월 31일 | `SalesRevenueNet` -> `Revenues` |

## 공통 수집 지표

| metric_name | 의미 | fact type | 기본 concept |
|---|---|---|---|
| `revenue` | 회계연도 수익 또는 매출 | duration | 기업별 후보에서 선택
| `net_income` | 회계연도 순이익 | duration | `NetIncomeLoss` |
| `assets` | 결산일 자산 총액 | instant | `Assets` |
| `liabilities` | 결산일 부채 총액 | instant | `Liabilities` |
| `operating_cash_flow` | 회계연도 영업활동 현금흐름 | duration | `NetCashProvidedByUsedInOperatingActivities` |
