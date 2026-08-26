# Historical Astronomical Data × Financial Markets
## Technical Research Blueprint

> **研究目标**  
> 建立一个可复现、无前视偏差的历史天文状态数据库，并把传统“占星学描述”转换成连续数学变量，用金融计量、机器学习和严格的 Out-of-Sample 方法检验：
>
> **天体状态是否对资产收益、波动率、风险偏好或极端事件存在稳定的增量预测信息。**

---

## 1. 核心研究问题

整个研究不预设“占星有效”，而是把天文状态视为一组：

- 完全外生
- 确定性
- 周期性
- 可提前计算

的时间变量。

核心问题定义为：

\[
I(Y_{t+h}; X_t \mid Z_t) > 0 \ ?
\]

其中：

- \(X_t\)：Astronomical / Astrology Features
- \(Y_{t+h}\)：未来金融结果
- \(Z_t\)：市场、宏观和日历控制变量
- \(I(\cdot)\)：条件信息量

最终真正需要回答的不是：

> “某个星象是不是神奇地对应上涨？”

而是：

> **在控制普通金融信息之后，天文状态是否还能提供稳定、可复现、OOS 有效的增量信息。**

---

# 2. 总体系统架构

```text
             ┌────────────────────┐
             │ JPL DE440 / DE441  │
             │ Swiss Ephemeris    │
             └─────────┬──────────┘
                       ↓
         ┌─────────────────────────────┐
         │ Layer 1 Astronomical State │
         │ 天体绝对位置 / 速度 / 距离 │
         └─────────────┬───────────────┘
                       ↓
         ┌─────────────────────────────┐
         │ Layer 2 Geometry Features   │
         │ 夹角 / 周期 / 相位 / 黄纬 │
         └─────────────┬───────────────┘
                       ↓
         ┌─────────────────────────────┐
         │ Layer 3 Astrology Encoding │
         │ 星座 / 相位 / 逆行 / 宫位 │
         └─────────────┬───────────────┘
                       ↓
         ┌─────────────────────────────┐
         │ Layer 4 Financial Dataset   │
         │ Prices / Vol / Macro / Flow│
         └─────────────┬───────────────┘
                       ↓
         ┌─────────────────────────────┐
         │ Layer 5 Statistical Tests  │
         │ IC / Event / Regression    │
         └─────────────┬───────────────┘
                       ↓
         ┌─────────────────────────────┐
         │ Layer 6 ML / OOS / Backtest│
         │ Purged CV / Walk Forward   │
         └─────────────┬───────────────┘
                       ↓
         ┌─────────────────────────────┐
         │ Layer 7 Falsification      │
         │ Placebo / FDR / Bootstrap  │
         └─────────────────────────────┘
```

---

# 3. 天文数据源设计

## 3.1 Ground Truth：NASA JPL

### 近现代金融研究

建议主数据源使用：

\[
\boxed{\text{JPL DE440}}
\]

原因：

- 覆盖 1550–2650
- 对现代时期精度极高
- 足够覆盖全部现代金融市场

### 超长历史研究

如果未来扩展到更长历史：

\[
\boxed{\text{JPL DE441}}
\]

DE441 主要优势是时间跨度极长。

因此推荐：

```text
1900–2026 主研究：
DE440

超长历史研究：
DE441
```

---

# 4. Swiss Ephemeris 的定位

Swiss Ephemeris 不作为唯一 Ground Truth。

推荐架构：

```text
JPL
↓
物理/天文学基准数据

Swiss Ephemeris
↓
占星坐标转换 / houses / nodes / zodiac / retrograde
```

因此：

\[
\boxed{
JPL = Truth\ Layer
}
\]

\[
\boxed{
SwissEph = Astrology\ Feature\ Layer
}
\]

---

# 5. 时间系统必须严格设计

底层数据库不能只存：

```text
2025-01-01
```

建议至少保留：

```text
timestamp_utc
JD_UTC
JD_TT
TDB
UT1
```

原因：

天文学计算实际涉及：

\[
UTC,\ UT1,\ TT,\ TDB
\]

所有底层数据统一使用：

\[
\boxed{\text{UTC}}
\]

例如：

```text
2025-01-01 00:00:00 UTC
2025-01-01 01:00:00 UTC
...
```

金融数据另外保留：

```text
timestamp_exchange_local
timestamp_utc
```

例如：

```text
NYSE Close:
2025-01-02 16:00 America/New_York

↓ 转换

2025-01-02 21:00 UTC
```

最终才能严格构造：

\[
X_{t,\ astro}
\rightarrow
R_{t+1}
\]

避免时间错位与前视偏差。

---

# 6. 第一层数据库：Astronomical State

推荐建立：

## `astro_state_hourly`

频率：

\[
\boxed{Hourly}
\]

1900–2026：

\[
126 \times 365.25 \times 24
\approx 1.10m
\]

约 110 万行，数据量非常小。

---

## 6.1 天体集合

建议第一版包含：

```text
Sun
Moon
Mercury
Venus
Mars
Jupiter
Saturn
Uranus
Neptune
Pluto
```

---

## 6.2 每个天体保存字段

| Variable | 含义 |
|---|---|
| `lon` | 黄经 |
| `lat` | 黄纬 |
| `distance` | 与地球距离 |
| `lon_velocity` | 黄经速度 |
| `lat_velocity` | 黄纬速度 |
| `distance_velocity` | 径向速度 |
| `RA` | 赤经 |
| `Dec` | 赤纬 |
| `heliocentric_lon` | 日心黄经 |
| `geocentric_lon` | 地心黄经 |

最核心变量：

\[
\lambda_i(t)
\]

即行星黄经。

---

# 7. 周期变量编码

黄经不能直接以：

\[
0^\circ \sim 360^\circ
\]

作为普通数值变量。

例如：

```text
359.9°
0.1°
```

真实距离只有：

\[
0.2^\circ
\]

但普通模型会把它视为巨大跳跃。

因此必须使用 circular encoding：

\[
x_{i,1}
=
\sin(\lambda_i)
\]

\[
x_{i,2}
=
\cos(\lambda_i)
\]

最终每个天体至少生成：

```text
planet_lon_sin
planet_lon_cos
```

---

# 8. Pairwise Geometry

真正值得研究的变量之一，是天体之间的相对几何关系。

对于任意两个天体：

\[
i,j
\]

定义最小夹角：

\[
\Delta_{ij}
=
\min(
|\lambda_i-\lambda_j|,
360-|\lambda_i-\lambda_j|
)
\]

范围：

\[
0^\circ \leq \Delta_{ij} \leq 180^\circ
\]

10 个天体共有：

\[
{10 \choose 2}=45
\]

个 pair。

---

# 9. Traditional Aspect：连续化

传统占星常见相位：

\[
A_k \in
\{0,60,90,120,180\}
\]

分别对应：

- Conjunction
- Sextile
- Square
- Trine
- Opposition

不要定义：

```text
angle ∈ [87°,93°] → 1
otherwise → 0
```

推荐定义距离：

\[
D_{ij,k}
=
|\Delta_{ij}-A_k|
\]

再定义连续 score：

\[
AspectScore
=
\exp
\left(
-\frac{D^2}{2\sigma^2}
\right)
\]

例如：

\[
\sigma=3^\circ
\]

这样：

```text
90° → 1.00
88° → 高
85° → 中
80° → 接近 0
```

---

# 10. 不预设传统相位：Fourier Encoding

更严格的做法是不告诉模型：

> 0°、60°、90°、120°、180° 特别重要。

对于：

\[
\theta_{ij}
=
\lambda_i-\lambda_j
\]

生成：

\[
\sin(k\theta_{ij})
\]

\[
\cos(k\theta_{ij})
\]

其中：

\[
k=1,2,\dots,K
\]

第一版建议：

\[
K=4\sim6
\]

这样模型可以自己识别：

- 360°
- 180°
- 120°
- 90°
- 72°
- 60°

等周期结构。

---

# 11. Retrograde / Station

传统逆行定义：

\[
v_{\lambda,i}<0
\]

因此：

\[
Retrograde_i=
1(v_{\lambda,i}<0)
\]

但不应只保留二元变量。

同时保存：

```text
longitude_velocity
retrograde
station_score
days_since_station
days_to_station
```

Station 可定义：

\[
|v_i| \approx 0
\]

推荐连续 station score：

\[
StationScore_i
=
\exp
\left(
-\frac{v_i^2}{2\sigma_v^2}
\right)
\]

---

# 12. Moon 单独建模

月球时间尺度和外行星完全不同。

月球公转周期约：

\[
27.3\text{ days}
\]

因此需要单独构造。

定义 Moon-Sun 相位：

\[
\theta_{moon}
=
\lambda_{Moon}-\lambda_{Sun}
\]

传统：

```text
0°   New Moon
90°  First Quarter
180° Full Moon
270° Last Quarter
```

但模型输入推荐：

\[
\sin(\theta_{moon})
\]

\[
\cos(\theta_{moon})
\]

同时可增加：

```text
illumination
moon_distance
moon_latitude
moon_velocity
```

---

# 13. Astrology Feature Layer

在天文学层之上单独建立：

## `astrology_features`

包含：

```text
Sun_sign
Moon_sign
Mercury_sign
...
Mercury_retrograde
Mars_Jupiter_square_score
Jupiter_Saturn_conjunction_score
Sun_house
Moon_house
Ascendant
MC
IC
DSC
```

---

# 14. Geocentric vs Topocentric

如果研究全球金融市场，第一阶段建议：

\[
\boxed{\text{Geocentric}}
\]

因为它：

- 不依赖城市
- 不依赖交易所
- 是全球唯一状态

---

## 14.1 Houses / Ascendant

Ascendant、MC、Houses 依赖：

\[
(time, latitude, longitude)
\]

因此：

```text
S&P 500
→ NYSE location

CSI300
→ Shanghai location
```

BTC 没有天然地理中心。

因此：

\[
\boxed{
BTC 第一阶段不使用 Houses
}
\]

---

# 15. 三个 Feature Universe

建议研究时严格拆成三层。

## Universe A — Physics

仅使用：

```text
planet longitude
latitude
velocity
distance
pair angle
moon phase
```

记为：

\[
X_A
\]

---

## Universe B — Geometry

增加：

```text
pair sin/cos
Fourier harmonics
station
relative angular velocity
```

记为：

\[
X_B
\]

---

## Universe C — Astrology

增加：

```text
zodiac
retrograde
traditional aspects
orb
houses
ascendant
```

记为：

\[
X_C
\]

然后比较：

\[
Performance(X_A)
\]

\[
Performance(X_B)
\]

\[
Performance(X_C)
\]

---

# 16. 金融 Target 设计

不要只预测：

> 明天上涨还是下跌。

建议建立多个 Target。

---

## 16.1 Forward Return

\[
R_{t,t+h}
=
\ln
\frac{P_{t+h}}{P_t}
\]

其中：

\[
h=
1D,5D,10D,20D,60D
\]

---

## 16.2 Excess Return

\[
AR_{t+h}
=
R_{asset,t+h}
-
\beta R_{market,t+h}
\]

---

## 16.3 Realized Volatility

\[
RV_{t:t+h}
\]

---

## 16.4 Tail Risk

例如：

\[
1(R_{t+5}<-5\%)
\]

---

## 16.5 Drawdown

\[
DD_{20d}
\]

---

## 16.6 Risk Regime

```text
Risk-on
Neutral
Risk-off
```

建议同时测试：

\[
E[R|X]
\]

和：

\[
E[|R||X]
\]

以及：

\[
P(Crash|X)
\]

---

# 17. 第一阶段资产池

推荐：

| Asset | 研究用途 |
|---|---|
| S&P 500 | 美国风险资产 |
| Nasdaq | Growth / Tech |
| Russell 2000 | Small Cap |
| Gold | 避险 |
| Silver | 贵金属 |
| WTI | 商品 |
| US 10Y | 利率 |
| DXY | 美元 |
| BTC | Crypto |
| VIX | 风险偏好 |

第二阶段扩展：

```text
HSI
CSI300
Nikkei
EuroStoxx
Copper
Natural Gas
ETH
```

---

# 18. 金融控制变量

必须控制普通市场因素。

回归框架：

\[
R_{t+h}
=
\alpha
+
\beta X^{astro}_t
+
\gamma Z_t
+
\epsilon
\]

其中：

\[
Z_t
\]

至少包括：

```text
Day of week
Month
Day of month
Turn-of-month
Quarter
Holiday
Option expiry
Past return
Momentum
Realized volatility
VIX
Term spread
DXY
Rates
```

最终最重要：

\[
\boxed{\beta}
\]

在控制这些变量之后是否仍然稳定存在。

---

# 19. 第一层统计：IC

对每一个 astronomical feature：

\[
IC_h
=
Corr(X_t,R_{t+h})
\]

建议至少计算：

```text
Pearson
Spearman
Mutual Information
Distance Correlation
```

同时分析：

\[
ICIR
=
\frac{\overline{IC}}{\sigma(IC)}
\]

不能只看全样本单个 correlation。

必须计算：

```text
10Y rolling IC
20Y rolling IC
```

检查稳定性。

---

# 20. Event Study

例如 Mercury Retrograde。

定义：

\[
\tau=0
\]

为逆行开始。

观察：

\[
CAR_{[-20,+20]}
\]

对所有历史 episode 计算：

\[
E[CAR_\tau]
\]

及：

- Bootstrap confidence interval
- HAC-adjusted significance
- Cross-period stability

---

# 21. Conditional Return Surface

对于：

\[
\theta=
Mars-Jupiter\ Angle
\]

不要先定义 Square。

直接估计：

\[
E[R_{t+20}\mid\theta]
\]

可采用：

```text
Kernel Regression
GAM
Spline
Fourier Regression
```

研究真实角度 response surface。

---

# 22. 模型分层

不要一开始直接 LightGBM。

建立四层模型。

---

## M0 — Financial Baseline

\[
Y=f(Z)
\]

只使用普通金融变量。

---

## M1 — Astro Only

\[
Y=f(X_{astro})
\]

---

## M2 — Incremental Astro

\[
Y=f(Z,X_{astro})
\]

---

## M3 — Nonlinear

```text
LightGBM
XGBoost
Random Forest
MLP
```

真正关心的是：

\[
\boxed{
Performance(M2)-Performance(M0)
}
\]

而不是：

> M2 本身能不能预测股票。

---

# 23. Out-of-Sample Framework

不能随机 shuffle。

例如：

```text
1900–1979
TRAIN

1980–1999
VALIDATION

2000–2026
OOS
```

更推荐 Walk-Forward：

```text
Train 1900–1969 → Test 1970–79
Train 1900–1979 → Test 1980–89
Train 1900–1989 → Test 1990–99
Train 1900–1999 → Test 2000–09
Train 1900–2009 → Test 2010–19
Train 1900–2019 → Test 2020–26
```

---

# 24. Purged Cross Validation

如果：

\[
Y_t=R_{t:t+30}
\]

那么：

```text
Jan 1 → Jan 31
Jan 2 → Feb 1
```

高度重叠。

普通 K-Fold 会高估效果。

必须使用：

\[
\boxed{
Purged\ K-Fold + Embargo
}
\]

若 holding horizon = 30d：

建议至少 purge：

\[
30d
\]

左右。

---

# 25. Multiple Testing

这是整个研究中最危险的问题。

如果有：

- 10 planets
- 45 pairs
- 多个 harmonic
- 多个 horizon
- 多个 asset
- 多种 transform

很容易产生：

\[
>100,000
\]

个 hypothesis。

若只使用：

\[
p<0.05
\]

即使所有变量完全无效，也会出现大量假阳性。

---

# 26. FDR

至少使用：

## Benjamini-Hochberg

控制：

\[
FDR
\]

对于最终最重要 hypothesis，可使用：

## Bonferroni

\[
\alpha^*
=
\frac{0.05}{N}
\]

---

# 27. Data Snooping Tests

建议增加：

```text
White's Reality Check
Hansen SPA
```

因为研究过程实际上是在：

> 从大量 astronomical / astrology strategy 中选择最优秀结果。

必须测试最佳表现是否只是：

\[
Data\ Snooping
\]

造成的。

---

# 28. Placebo Universe

强烈建议建立一整套假宇宙。

---

## Placebo A — Time Shift

\[
X_{t+137d}
\]

---

## Placebo B — Longer Shift

\[
X_{t+503d}
\]

---

## Placebo C — Planet Phase Shift

\[
\lambda_i(t)+c_i
\]

---

## Placebo D — Phase Randomization

保持周期结构，但随机化 phase。

最终要求：

\[
Performance_{real}
>
P_{99\%}
(
Performance_{placebo}
)
\]

才认为结果有价值。

---

# 29. Fake Zodiac Test

传统 Zodiac：

\[
30^\circ
\]

一宫。

创造多个 alternative zodiac：

```text
每宫 27°
每宫 31°
整体旋转 +7°
整体旋转 +13°
整体旋转 +23°
...
```

然后比较：

\[
Performance_{traditional}
\]

是否优于：

\[
Performance_{random\ zodiac}
\]

这直接检验：

> 传统 Zodiac 定义本身是否具有额外信息。

---

# 30. 两个 Null Hypothesis

## H1 — Astronomy Null

\[
H_0:
X_{astro}
\not\rightarrow
Financial\ Market
\]

---

## H2 — Astrology Null

即使 astronomical cycles 有效：

\[
H_0:
Traditional\ Astrology
\]

并不比纯数学 astronomical encoding 提供更多信息。

---

# 31. 数据库设计

推荐：

\[
\boxed{
DuckDB + Parquet
}
\]

不需要一开始使用 PostgreSQL。

---

## 31.1 项目目录

```text
astro_quant/
│
├── data/
│   ├── raw/
│   │   ├── jpl/
│   │   └── market/
│   │
│   ├── astro/
│   │   ├── astro_state_hourly.parquet
│   │   ├── astro_pairwise.parquet
│   │   ├── astrology_features.parquet
│   │   └── astro_events.parquet
│   │
│   └── market/
│       ├── daily_prices.parquet
│       ├── macro.parquet
│       └── factors.parquet
│
├── src/
│   ├── ephemeris.py
│   ├── coordinates.py
│   ├── aspects.py
│   ├── events.py
│   ├── market_data.py
│   ├── features.py
│   ├── targets.py
│   ├── statistics.py
│   ├── backtest.py
│   └── placebo.py
│
├── configs/
│   ├── planets.yaml
│   ├── aspects.yaml
│   └── experiments.yaml
│
├── notebooks/
│
├── tests/
│
└── results/
```

---

# 32. 核心 Feature Schema

最终不要只存：

```text
date
SunSign
MoonSign
MarsSign
```

而应该至少包括：

```text
date

sun_lon_sin
sun_lon_cos
sun_velocity

moon_lon_sin
moon_lon_cos
moon_velocity
moon_phase_sin
moon_phase_cos

mercury_lon_sin
mercury_lon_cos
mercury_velocity
mercury_retrograde

mars_jupiter_angle_sin
mars_jupiter_angle_cos
mars_jupiter_2x_sin
mars_jupiter_2x_cos

jupiter_saturn_angle_sin
jupiter_saturn_angle_cos
...
```

---

# 33. 第一版 Feature 数量

建议控制在：

\[
\boxed{
250-300
}
\]

左右。

估算：

### Planetary State

\[
10
\times
(\sin\lambda,\cos\lambda,v)
=
30
\]

### Pair Geometry

\[
45\times2
=
90
\]

### Second Harmonic

\[
90
\]

### Moon Features

\[
10
\]

### Retrograde / Station

\[
20
\]

### Distance / Latitude

\[
30-50
\]

总计约：

\[
250-300
\]

---

# 34. Factor Research Pipeline

推荐严格执行：

```text
Raw Astronomical State
↓
Mathematical Basis
↓
Univariate Screening
↓
Stability Screening
↓
Redundancy Removal
↓
Validation
↓
OOS
↓
Economic Significance
↓
Backtest
```

核心目标不是：

> 找“最强星象”。

而是：

\[
\boxed{
Reproducible\ Information\ Structure
}
\]

---

# 35. Feature Survival Standard

一个 feature 要进入下一阶段，至少要求：

\[
IC_{train}>0
\]

且：

\[
IC_{validation}>0
\]

并且 rolling windows 中方向稳定。

例如：

\[
P
(
sign(IC_t)
=
sign(\bar{IC})
)
>
70\%
\]

最终：

\[
IC_{OOS}>0
\]

---

# 36. Strategy-Level Metrics

最终策略需要检查：

```text
Sharpe
Sortino
Calmar
Maximum Drawdown
Turnover
Hit Rate
Skew
Tail Loss
Capacity
Transaction Cost Sensitivity
```

其中最重要的是：

\[
\boxed{
Sharpe_{OOS}
}
\]

而非 In-Sample Sharpe。

---

# 37. Cross-Asset Risk Factor

如果 astronomical effect 真的是全球风险偏好变化，则可能表现为：

```text
Stocks ↑
VIX ↓
Credit Spread ↓
Gold ↓ / Mixed
USD ↓ / Mixed
```

因此可以构造：

\[
Risk_t
=
w_1 SPX
-w_2 VIX
-w_3 CreditSpread
-w_4 USD
+\cdots
\]

再检验：

\[
X_{astro}
\rightarrow
Risk_{t+h}
\]

这可能比单资产预测更有意义。

---

# 38. Regime Conditional Effect

可能存在：

\[
X_{astro}
\]

本身没有 unconditional alpha。

但：

\[
X_{astro}
\times
Regime_t
\]

有信息。

例如：

\[
R_{t+h}
=
\alpha
+
\beta_1 Astro_t
+
\beta_2 VIX_t
+
\beta_3 Astro_t\times VIX_t
+
\epsilon
\]

研究：

> 某类 astronomical phase 是否只在高波动、风险厌恶、tightening regime 下有不同表现。

---

# 39. 最重要的统计陷阱：周期伪相关

天体运动本质：

\[
X_t=f(t)
\]

是时间的确定性函数。

而金融市场本身也存在：

- Seasonality
- Business Cycle
- Regime
- Secular Trend
- Calendar Effect

因此：

\[
Corr(f(t),Y_t)
\]

非常容易产生 spurious correlation。

---

# 40. Random Periodic Benchmark

必须生成大量随机周期函数：

\[
\sin
\left(
\frac{2\pi t}{P}
+
\phi
\right)
\]

其中：

\[
P\in[20d,100y]
\]

\[
\phi \sim U(0,2\pi)
\]

然后比较：

\[
Astronomical\ Factor
\]

是否显著优于：

\[
Random\ Periodic\ Factor
\]

---

# 41. 四层 Null Benchmark

最终建议构建：

| Benchmark | 检验内容 |
|---|---|
| Random Noise | 最低层 Null |
| Random Phase Astronomy | 是否只是天体周期 |
| Random Fourier Cycles | 任意周期是否也能做到 |
| Fake Astrology | 传统 Astrology 是否特殊 |

理想的 hierarchy：

\[
\boxed{
Real\ Astrology
>
Real\ Astronomy
>
Random\ Periodicity
>
Noise
}
\]

如果：

\[
Real\ Astrology
\approx
Random\ Periodicity
\]

则应认为没有可靠的 astrology signal。

---

# 42. 项目实施阶段

## Phase I — Data Infrastructure

时间：

\[
1900-2026
\]

建立：

```text
JPL Ephemeris
Hourly State
10 Planets
Moon Data
Pairwise Geometry
Station / Retrograde
Traditional Aspects
```

这一阶段：

\[
\boxed{
完全不看金融结果
}
\]

避免 researcher degrees of freedom。

---

## Phase II — Exploratory Research

研究：

\[
X_t
\rightarrow
\{
Return,
Volatility,
Drawdown,
Risk
\}
\]

输出：

```text
IC Heatmap
Angle-Response Curve
Event Study
Fourier Spectrum
Rolling IC
Cross-Asset Consistency
```

这一阶段不做策略优化。

---

## Phase III — Confirmatory Testing

在预留数据：

\[
2000-2026
\]

上执行固定 hypothesis。

加入：

```text
FDR
Bootstrap
HAC SE
Reality Check
Placebo Universe
```

---

## Phase IV — Alpha Model

只有 survive 的 factor 才允许进入：

```text
Linear
Ridge
GAM
LightGBM
```

然后比较：

\[
Baseline
\]

vs.

\[
Baseline+Astro
\]

---

## Phase V — Trading

最终才转成：

\[
Signal_t
\]

然后加入：

```text
Long / Short
Vol Targeting
Transaction Cost
Slippage
Risk Constraint
Turnover Constraint
```

---

# 43. 推荐第一版研究规模

## 时间范围

\[
\boxed{
1950-2026
}
\]

## 天文原始频率

\[
\boxed{
Hourly
}
\]

## 金融研究频率

\[
\boxed{
Daily
}
\]

## 天体

```text
Sun
Moon
Mercury
Venus
Mars
Jupiter
Saturn
Uranus
Neptune
Pluto
```

## Markets

```text
S&P 500
Gold
WTI
US10Y
DXY
VIX
BTC
```

BTC 使用其有可靠市场数据后的时期。

---

# 44. 第一版 Astrology Benchmark

传统变量控制在：

```text
Mercury Retrograde
Venus Retrograde
Mars Retrograde

New Moon
Full Moon

Conjunction
Sextile
Square
Trine
Opposition
```

重点 Pair：

```text
Jupiter-Saturn
Mars-Saturn
Mars-Jupiter
Sun-Jupiter
Sun-Saturn
Venus-Jupiter
Mercury-Jupiter
```

第一版不要加入：

```text
大量 asteroid
Lilith
Chiron
大量小众占星变量
```

否则极容易变成：

\[
p\text{-hacking machine}
\]

---

# 45. 技术栈

建议：

```text
Python
│
├── skyfield
├── pyswisseph
├── numpy
├── pandas / polars
├── scipy
├── statsmodels
├── scikit-learn
├── lightgbm
├── duckdb
└── pyarrow
```

---

# 46. 最终模型框架

定义：

\[
M_t
=
Market\ State
\]

\[
A_t
=
Astronomical\ State
\]

完整模型：

\[
Y_{t+h}
=
f(
M_t,
A_t,
A_t\times M_t
)
+
\epsilon
\]

---

## Baseline

\[
M_0=f(M_t)
\]

---

## Astro Only

\[
M_1=f(A_t)
\]

---

## Combined

\[
M_2=f(M_t,A_t)
\]

---

真正最重要的是：

\[
\boxed{
\Delta R^2
=
R^2(M_2)-R^2(M_0)
}
\]

以及：

\[
\boxed{
\Delta IC
}
\]

\[
\boxed{
\Delta Sharpe_{OOS}
}
\]

如果：

\[
\Delta R^2 \approx 0
\]

则 astronomical data 没有 incremental information。

---

# 47. 最终三个研究问题

## Question 1

### Astronomical Cycles 是否与金融市场存在统计关系？

\[
Astronomy
\rightarrow
Market?
\]

---

## Question 2

### 如果存在，是否只是普通周期性？

\[
Astronomy
>
Random\ Cycles?
\]

---

## Question 3

### 如果 Astronomy 有信息，传统 Astrology 是否进一步增加预测能力？

\[
Astrology
>
Astronomy?
\]

---

# 48. 最终研究 Hierarchy

整个研究可以抽象成：

\[
\boxed{
Noise
\rightarrow
Random\ Cycles
\rightarrow
Astronomy
\rightarrow
Astrology
}
\]

逐层做增量信息检验。

---

# 49. 最核心的方法论原则

整个项目不应该被定义为：

> 下载星象 → 找合相 → 回测收益率。

而应该定义成：

\[
\boxed{
\text{Do deterministic astronomical states contain incremental information about stochastic financial outcomes?}
}
\]

完整研究链路：

```text
Astronomical State
↓
Continuous Mathematical Encoding
↓
Financial Controls
↓
Out-of-Sample
↓
Multiple-Testing Correction
↓
Placebo Universe
↓
Incremental Information Test
```

---

# 50. 最重要的一条原则

> **一套严谨的星象金融研究框架，必须有能力得出“星象没有预测力”这个结论。**

如果整个研究框架只会不断寻找新的星象组合，直到发现显著结果，那么它本质上不是严谨的 Quant Research，而只是 Data Mining。

真正应该寻找的是：

\[
\boxed{
Stable
+
Out-of-Sample
+
Incremental
+
Economically Significant
+
Placebo-Resistant
}
\]

的信息结构。

---

# 51. 推荐下一步

下一版可以进一步把本文件扩展为真正可直接开发的：

## `Technical Specification v1.0`

内容包括：

1. 全部数据库字段定义  
2. 第一版 250–300 个 Feature 的完整数学公式  
3. JPL / Swiss Ephemeris 计算口径  
4. Market Target 定义  
5. Train / Validation / OOS 切割  
6. Purged CV 参数  
7. 20–30 个预注册 Hypothesis  
8. Placebo Universe 生成规则  
9. Backtest 规则  
10. Codex / Claude 可直接执行的工程任务拆分  

这样可以把：

\[
Research\ Idea
\]

直接转化成：

\[
Reproducible\ Research\ System
\]

