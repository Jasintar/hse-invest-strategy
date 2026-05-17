# Документация к полям фундаментальных данных (Alpha Vantage)

Все данные загружаются через Alpha Vantage API и сохраняются в формате CSV.  
Структура хранения: `data/{Сектор}/{ТИКЕР}/{тип_отчёта}.csv`

---

## 1. overview.csv — Обзор компании

| Поле | Описание |
|------|----------|
| `Symbol` | Тикер (биржевой символ) компании |
| `AssetType` | Тип актива (Common Stock, ETF и т.д.) |
| `Name` | Полное официальное название компании |
| `Description` | Краткое описание деятельности компании |
| `CIK` | Идентификатор SEC (регулятор США) |
| `Exchange` | Биржа (NYSE, NASDAQ и т.д.) |
| `Currency` | Валюта отчётности |
| `Country` | Страна регистрации |
| `Sector` | Сектор экономики (Technology, Healthcare и т.д.) |
| `Industry` | Отрасль внутри сектора |
| `Address` | Юридический адрес компании |
| `OfficialSite` | Официальный сайт |
| `FiscalYearEnd` | Месяц окончания финансового года |
| `LatestQuarter` | Дата последнего отчётного квартала |
| `MarketCapitalization` | Рыночная капитализация (USD) |
| `EBITDA` | EBITDA — прибыль до вычета процентов, налогов, амортизации (USD) |
| `PERatio` | P/E — цена к прибыли на акцию |
| `PEGRatio` | PEG — P/E с учётом роста прибыли |
| `BookValue` | Балансовая стоимость на одну акцию (USD) |
| `DividendPerShare` | Дивиденд на акцию (USD) |
| `DividendYield` | Дивидендная доходность (доли единицы, напр. 0.03 = 3%) |
| `EPS` | EPS — прибыль на акцию (USD) |
| `RevenuePerShareTTM` | Выручка на акцию за последние 12 месяцев (USD) |
| `ProfitMargin` | Чистая рентабельность (чистая прибыль / выручка) |
| `OperatingMarginTTM` | Операционная рентабельность за TTM |
| `ReturnOnAssetsTTM` | ROA — рентабельность активов за TTM |
| `ReturnOnEquityTTM` | ROE — рентабельность собственного капитала за TTM |
| `RevenueTTM` | Выручка за последние 12 месяцев (USD) |
| `GrossProfitTTM` | Валовая прибыль за последние 12 месяцев (USD) |
| `DilutedEPSTTM` | Разводнённая прибыль на акцию за TTM (USD) |
| `QuarterlyEarningsGrowthYOY` | Рост прибыли квартал-к-кварталу год-к-году |
| `QuarterlyRevenueGrowthYOY` | Рост выручки квартал-к-кварталу год-к-году |
| `AnalystTargetPrice` | Целевая цена по консенсусу аналитиков (USD) |
| `AnalystRatingStrongBuy` | Кол-во рекомендаций "активно покупать" |
| `AnalystRatingBuy` | Кол-во рекомендаций "покупать" |
| `AnalystRatingHold` | Кол-во рекомендаций "держать" |
| `AnalystRatingSell` | Кол-во рекомендаций "продавать" |
| `AnalystRatingStrongSell` | Кол-во рекомендаций "активно продавать" |
| `TrailingPE` | P/E на основе прошлых данных |
| `ForwardPE` | P/E на основе прогнозной прибыли |
| `PriceToSalesRatioTTM` | P/S — цена к выручке за TTM |
| `PriceToBookRatio` | P/B — цена к балансовой стоимости |
| `EVToRevenue` | EV/Revenue — стоимость компании к выручке |
| `EVToEBITDA` | EV/EBITDA — стоимость компании к EBITDA |
| `Beta` | Бета-коэффициент (волатильность относительно рынка) |
| `52WeekHigh` | Максимум цены за последние 52 недели (USD) |
| `52WeekLow` | Минимум цены за последние 52 недели (USD) |
| `50DayMovingAverage` | Скользящая средняя за 50 дней (USD) |
| `200DayMovingAverage` | Скользящая средняя за 200 дней (USD) |
| `SharesOutstanding` | Кол-во акций в обращении |
| `DividendDate` | Дата выплаты дивиденда |
| `ExDividendDate` | Дата отсечки под дивиденд |

---

## 2. income_statement_annual.csv / income_statement_quarterly.csv — Отчёт о прибылях и убытках

Годовые данные: последние ~20 лет. Квартальные: последние ~5 лет (20 кварталов).

| Поле | Описание |
|------|----------|
| `fiscalDateEnding` | Дата окончания отчётного периода |
| `reportedCurrency` | Валюта отчётности |
| `grossProfit` | Валовая прибыль = Выручка − Себестоимость (USD) |
| `totalRevenue` | Общая выручка (USD) |
| `costOfRevenue` | Себестоимость реализованной продукции/услуг (USD) |
| `costofGoodsAndServicesSold` | Стоимость проданных товаров и услуг (USD) |
| `operatingIncome` | Операционная прибыль (USD) |
| `sellingGeneralAndAdministrative` | Коммерческие, общие и административные расходы (USD) |
| `researchAndDevelopment` | Расходы на НИОКР (исследования и разработки) (USD) |
| `operatingExpenses` | Общие операционные расходы (USD) |
| `investmentIncomeNet` | Чистый доход от инвестиций (USD) |
| `netInterestIncome` | Чистый процентный доход (USD) |
| `interestIncome` | Процентные доходы (USD) |
| `interestExpense` | Процентные расходы (USD) |
| `nonInterestIncome` | Непроцентные доходы (USD) |
| `otherNonOperatingIncome` | Прочие внеоперационные доходы (USD) |
| `depreciation` | Амортизация основных средств (USD) |
| `depreciationAndAmortization` | Амортизация всех активов (материальных + нематериальных) (USD) |
| `incomeBeforeTax` | Прибыль до налогообложения (USD) |
| `incomeTaxExpense` | Расходы по налогу на прибыль (USD) |
| `interestAndDebtExpense` | Расходы по процентам и долгу (USD) |
| `netIncomeFromContinuingOperations` | Чистая прибыль от продолжающихся операций (USD) |
| `comprehensiveIncomeNetOfTax` | Совокупный доход за вычетом налогов (USD) |
| `ebit` | EBIT — прибыль до вычета процентов и налогов (USD) |
| `ebitda` | EBITDA — прибыль до вычета процентов, налогов и амортизации (USD) |
| `netIncome` | Чистая прибыль (итоговая прибыль компании) (USD) |

---

## 3. balance_sheet_annual.csv / balance_sheet_quarterly.csv — Бухгалтерский баланс

| Поле | Описание |
|------|----------|
| `fiscalDateEnding` | Дата окончания отчётного периода |
| `reportedCurrency` | Валюта отчётности |
| **АКТИВЫ** | |
| `totalAssets` | Итого активов (USD) |
| `totalCurrentAssets` | Итого оборотных активов (USD) |
| `cashAndCashEquivalentsAtCarryingValue` | Денежные средства и эквиваленты (USD) |
| `cashAndShortTermInvestments` | Денежные средства и краткосрочные вложения (USD) |
| `inventory` | Запасы (товарно-материальные ценности) (USD) |
| `currentNetReceivables` | Дебиторская задолженность (текущая) (USD) |
| `totalNonCurrentAssets` | Итого внеоборотных активов (USD) |
| `propertyPlantEquipment` | Основные средства (здания, оборудование) (USD) |
| `accumulatedDepreciationAmortizationPPE` | Накопленная амортизация основных средств (USD) |
| `intangibleAssets` | Нематериальные активы (USD) |
| `intangibleAssetsExcludingGoodwill` | Нематериальные активы без гудвила (USD) |
| `goodwill` | Гудвил (деловая репутация, превышение цены покупки над балансовой стоимостью) (USD) |
| `investments` | Инвестиции всего (USD) |
| `longTermInvestments` | Долгосрочные инвестиции (USD) |
| `shortTermInvestments` | Краткосрочные инвестиции (USD) |
| `otherCurrentAssets` | Прочие оборотные активы (USD) |
| `otherNonCurrentAssets` | Прочие внеоборотные активы (USD) |
| **ОБЯЗАТЕЛЬСТВА** | |
| `totalLiabilities` | Итого обязательств (USD) |
| `totalCurrentLiabilities` | Итого краткосрочных обязательств (USD) |
| `currentAccountsPayable` | Кредиторская задолженность (текущая) (USD) |
| `deferredRevenue` | Отложенная (авансовая) выручка (USD) |
| `currentDebt` | Краткосрочный долг (USD) |
| `shortTermDebt` | Краткосрочные займы (USD) |
| `totalNonCurrentLiabilities` | Итого долгосрочных обязательств (USD) |
| `capitalLeaseObligations` | Обязательства по финансовой аренде (USD) |
| `longTermDebt` | Долгосрочный долг (USD) |
| `currentLongTermDebt` | Текущая часть долгосрочного долга (USD) |
| `longTermDebtNoncurrent` | Долгосрочный долг (нетекущий) (USD) |
| `shortLongTermDebtTotal` | Суммарный долг (краткосрочный + долгосрочный) (USD) |
| `otherCurrentLiabilities` | Прочие краткосрочные обязательства (USD) |
| `otherNonCurrentLiabilities` | Прочие долгосрочные обязательства (USD) |
| **СОБСТВЕННЫЙ КАПИТАЛ** | |
| `totalShareholderEquity` | Итого собственного капитала акционеров (USD) |
| `treasuryStock` | Казначейские акции (выкупленные у рынка) (USD) |
| `retainedEarnings` | Нераспределённая прибыль (USD) |
| `commonStock` | Обыкновенные акции по номинальной стоимости (USD) |
| `commonStockSharesOutstanding` | Количество обыкновенных акций в обращении (шт.) |

---

## 4. cash_flow_annual.csv / cash_flow_quarterly.csv — Отчёт о движении денежных средств

| Поле | Описание |
|------|----------|
| `fiscalDateEnding` | Дата окончания отчётного периода |
| `reportedCurrency` | Валюта отчётности |
| **ОПЕРАЦИОННАЯ ДЕЯТЕЛЬНОСТЬ** | |
| `operatingCashflow` | Чистый денежный поток от операционной деятельности (USD) |
| `paymentsForOperatingActivities` | Выплаты по операционной деятельности (USD) |
| `proceedsFromOperatingActivities` | Поступления от операционной деятельности (USD) |
| `changeInOperatingLiabilities` | Изменение операционных обязательств (USD) |
| `changeInOperatingAssets` | Изменение операционных активов (USD) |
| `depreciationDepletionAndAmortization` | Амортизация (неденежная статья, прибавляется обратно) (USD) |
| `capitalExpenditures` | Капитальные затраты (CAPEX) — покупка оборудования и т.п. (USD, отрицательное) |
| `changeInReceivables` | Изменение дебиторской задолженности (USD) |
| `changeInInventory` | Изменение запасов (USD) |
| `profitLoss` | Чистая прибыль/убыток (USD) |
| **ИНВЕСТИЦИОННАЯ ДЕЯТЕЛЬНОСТЬ** | |
| `cashflowFromInvestment` | Денежный поток от инвестиционной деятельности (USD) |
| **ФИНАНСОВАЯ ДЕЯТЕЛЬНОСТЬ** | |
| `cashflowFromFinancing` | Денежный поток от финансовой деятельности (USD) |
| `proceedsFromRepaymentsOfShortTermDebt` | Поступления от погашения краткосрочного долга (USD) |
| `paymentsForRepurchaseOfCommonStock` | Выплаты на выкуп обыкновенных акций (buyback) (USD) |
| `paymentsForRepurchaseOfEquity` | Выплаты на выкуп акционерного капитала (USD) |
| `paymentsForRepurchaseOfPreferredStock` | Выплаты на выкуп привилегированных акций (USD) |
| `dividendPayout` | Выплаченные дивиденды (USD) |
| `dividendPayoutCommonStock` | Дивиденды по обыкновенным акциям (USD) |
| `dividendPayoutPreferredStock` | Дивиденды по привилегированным акциям (USD) |
| `proceedsFromIssuanceOfCommonStock` | Поступления от размещения новых обыкновенных акций (USD) |
| `proceedsFromIssuanceOfLongTermDebtAndCapitalSecuritiesNet` | Поступления от размещения долгосрочного долга (чистые) (USD) |
| `proceedsFromIssuanceOfPreferredStock` | Поступления от размещения привилегированных акций (USD) |
| `proceedsFromRepurchaseOfEquity` | Поступления от выкупа акционерного капитала (USD) |
| `proceedsFromSaleOfTreasuryStock` | Поступления от продажи казначейских акций (USD) |
| `stockBasedCompensation` | Вознаграждение сотрудников акциями (SBC) (USD) |
| `changeInCashAndCashEquivalents` | Итоговое изменение денежных средств за период (USD) |
| `changeInExchangeRate` | Влияние курсовых разниц на денежные средства (USD) |
| `netIncome` | Чистая прибыль (из отчёта P&L) (USD) |

---

## 5. earnings_annual.csv — Прибыль на акцию (годовая)

| Поле | Описание |
|------|----------|
| `fiscalDateEnding` | Дата окончания финансового года |
| `reportedEPS` | Фактическая прибыль на акцию (EPS) за год (USD) |

---

## 6. earnings_quarterly.csv — Прибыль на акцию (квартальная)

| Поле | Описание |
|------|----------|
| `fiscalDateEnding` | Дата окончания квартала |
| `reportedDate` | Фактическая дата публикации отчёта |
| `reportedEPS` | Фактическая прибыль на акцию (USD) |
| `estimatedEPS` | Прогнозная прибыль на акцию по консенсусу аналитиков (USD) |
| `surprise` | Разница между фактическим и прогнозным EPS (USD) |
| `surprisePercentage` | Отклонение фактического EPS от прогноза в % |
| `reportTime` | Время публикации отчёта (до/после рынка: pre-market / post-market) |

---

## Справочник по ключевым финансовым метрикам

| Метрика | Формула / Суть |
|---------|---------------|
| **Gross Profit (Валовая прибыль)** | Выручка − Себестоимость |
| **EBIT** | Валовая прибыль − Операционные расходы (прибыль до % и налогов) |
| **EBITDA** | EBIT + Амортизация |
| **Net Income (Чистая прибыль)** | Прибыль после всех расходов и налогов |
| **Free Cash Flow (FCF)** | Операционный CF − CAPEX |
| **Current Ratio** | Оборотные активы / Краткосрочные обязательства (ликвидность) |
| **Debt-to-Equity** | Суммарный долг / Собственный капитал (леверидж) |
| **ROE** | Чистая прибыль / Собственный капитал |
| **ROA** | Чистая прибыль / Итого активов |
| **P/E** | Цена акции / EPS |
| **EV/EBITDA** | (Капитализация + Долг − Кэш) / EBITDA |

---

## Структура файлов

```
data/
├── ticker_sector_mapping.csv          ← маппинг тикеров по секторам
├── Technology/
│   ├── AAPL/
│   │   ├── overview.csv
│   │   ├── income_statement_annual.csv
│   │   ├── income_statement_quarterly.csv
│   │   ├── balance_sheet_annual.csv
│   │   ├── balance_sheet_quarterly.csv
│   │   ├── cash_flow_annual.csv
│   │   ├── cash_flow_quarterly.csv
│   │   ├── earnings_annual.csv
│   │   └── earnings_quarterly.csv
│   └── ...
├── Healthcare/
│   └── ...
└── ...
```

> **Примечание:** Значения `None` в CSV означают, что данные не были раскрыты компанией за этот период (характерно для банков и страховщиков — у них другие GAAP-стандарты).
