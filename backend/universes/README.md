# Universes

Constituent lists for non-A-share markets. A-share uses dynamic discovery via
akshare's `stock_info_a_code_name` + main-board filter, so no JSON is needed.

## Files

- `hstech.json` — Hang Seng TECH Index (~30 stocks). Source:
  https://www.hsi.com.hk/eng/indexes/all-indexes/hstech
- `russell1000_growth.json` — Russell 1000 Growth Index top holdings (~120 names
  covering ~85% of index weight). Source:
  https://www.ishares.com/us/products/239706/ishares-russell-1000-growth-etf

## Weekly refresh

Run every weekend. The `updated` field in each JSON records the last refresh
date. Index composition changes quarterly (HSTECH) / annually (Russell), but
weights shift weekly.

### HSTECH
Copy the constituent table from the HSI website and update the `stocks` array.
Code format: 5-digit zero-padded (e.g. `"00700"`).

### Russell 1000 Growth
Download IWF holdings CSV from iShares. Keep the top ~120 by weight for a
manageable daily scan. Add/remove entries to track the index.
Code format: standard US ticker (e.g. `"AAPL"`).

## Schema

```json
{
  "name": "<human readable>",
  "symbol": "<index ticker>",
  "updated": "YYYY-MM-DD",
  "note": "<free text>",
  "stocks": [ { "code": "...", "name": "..." }, ... ]
}
```
