# Companies

The project uses five companies with different business models and fiscal calendars. These labels are project groupings, rather than a claim that their financial metrics are directly comparable.

| Ticker | Company | CIK | Project grouping | Fiscal year end | Why it is included |
|---|---|---|---|---|---|
| AAPL | Apple Inc. | `0000320193` | Technology | Late September | Product and service revenue in the same business |
| MSFT | Microsoft Corporation | `0000789019` | Technology | June 30 | Software and cloud revenue |
| JPM | JPMorgan Chase & Co. | `0000019617` | Banking | December 31 | A bank balance sheet and exposure to the rate environment |
| TSLA | Tesla, Inc. | `0001318605` | Automotive and Energy | December 31 | A growth business spanning vehicles and energy |
| WMT | Walmart Inc. | `0000104169` | Retail | January 31 | Retail performance alongside consumer conditions |

Keep CIKs as ten-character strings, including leading zeros. Use the saved `period_start` and `period_end` fields for each row; the fiscal-year label alone is not a common calendar window across companies.

## Revenue concepts

The collector tries these US-GAAP concepts in order. The selected concept is retained in `revenue_concept`.

| Companies | Fallback order |
|---|---|
| AAPL, MSFT, TSLA | `RevenueFromContractWithCustomerExcludingAssessedTax`, then `Revenues` |
| JPM | `Revenues`, then `RevenueFromContractWithCustomerExcludingAssessedTax` |
| WMT | `RevenueFromContractWithCustomerExcludingAssessedTax`, then `SalesRevenueNet`, then `Revenues` |

## Other financial metrics

| Metric | US-GAAP concept | Reporting period |
|---|---|---|
| Net income | `NetIncomeLoss` | Fiscal year |
| Assets | `Assets` | Balance-sheet date |
| Liabilities | `Liabilities` | Balance-sheet date |
| Operating cash flow | `NetCashProvidedByUsedInOperatingActivities` | Fiscal year |

Banking assets, liabilities and revenue have a different economic meaning from the same broad categories in a technology or retail company. Compare each company's history before making a cross-company ranking.
