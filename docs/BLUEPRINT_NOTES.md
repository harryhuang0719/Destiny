# Blueprint implementation notes

The original 2,287-line research blueprint is preserved verbatim at
[Historical_Astronomical_Data_Financial_Markets_Research_Blueprint.md](Historical_Astronomical_Data_Financial_Markets_Research_Blueprint.md)
(SHA-256 `30274cdc059952e7ecf9f480bf1cb6e75a3365f14fc47d81e297571f9af15ec9`).

It is an ambitious research agenda, not a statement that every layer is already
implemented. Destiny 2 adopts its strongest principle—design the experiment so
“no predictive information” is a valid result—and makes the following
corrections explicit:

1. Swiss Ephemeris is AGPL/commercial dual-licensed, so the MIT implementation
   uses Skyfield/JPL only.
2. Strict UTC labels begin in 1972; earlier dates need a disclosed historical or
   proleptic policy while astronomy remains on TT/TDB/UT1.
3. A holdout chosen after its outcomes were already visible is pseudo-OOS, not a
   sealed confirmation. Prospective evidence starts after preregistration.
4. “1.1 million hourly rows” counts timestamps only. Ten normalized bodies imply
   roughly 11 million rows; 45 long-form pair tables would be much larger.
   Destiny therefore persists wide body-derived features only on requested grids.
5. S&P indexes, VIX, DXY, yields, WTI spot, futures, ETFs, and crypto are not one
   interchangeable asset class. Market targets are BYOD and must declare exact semantics.
6. Placebos and multiple-testing correction must cover the preregistered family;
   they cannot be applied only to the final winner.
7. Long-period features require enough independent cycles. Otherwise they stay descriptive.

The implementation contract and current limits live in
[references/historical-research.md](../references/historical-research.md).
