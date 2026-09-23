# Sentinel cases

Autonomous sweep of 2016-11-01 to 2016-12-31 over TigerGraph (via MCP), outside the 20 case-pack cards. Signals: device rings (device_ring_scan, 30-day windows, >= 3 cards New on a rare profile, <= 60 cards), structuring (near_threshold_scan $450-$500, >= 3 online txns within 60 min), model score (>= 2 txns scored >= 0.90 by the closed-case classifier within 48 h). Each alert is investigated by the same agent as the case pack.

| Case | Alert source | Card | Signal | Verdict | Pattern | p | Exposure | Final actions |
|---|---|---|---|---|---|---|---|---|
| SEN-001 | device_ring | C07472-K1 | device SM-G935F Build/NRD90M / Android 7.0 / chrome 62.0 for android / 1920x1080 New on 28 cards (28 anon proxy), 52 ever | fraud | undocumented | 0.90 | $265.85 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2), MONITOR_CONNECTED_CARDS (auto), ESCALATE_TO_ANALYST (auto) |
| SEN-002 | structuring | C05560-K2 | 3 online txns $450-$500 in 7 min | fraud | undocumented | 0.90 | $1,799.79 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-003 | structuring | C05423-K1 | 4 online txns $450-$500 in 30 min | fraud | undocumented | 0.90 | $1,884.76 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-004 | structuring | C03633-K1 | 4 online txns $450-$500 in 21 min | fraud | undocumented | 0.90 | $1,935.29 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-005 | structuring | C02716-K2 | 4 online txns $450-$500 in 60 min | fraud | undocumented | 0.90 | $2,499.89 | BLOCK_ALL_CARDS (L2), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-006 | structuring | C05766-K1 | 4 online txns $450-$500 in 30 min | fraud | undocumented | 0.90 | $1,908.26 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-007 | structuring | C02265-K1 | 4 online txns $450-$500 in 30 min | fraud | undocumented | 0.90 | $1,904.86 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-008 | structuring | C10990-K1 | 4 online txns $450-$500 in 24 min | fraud | undocumented | 0.90 | $1,926.93 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-009 | structuring | C12641-K2 | 4 online txns $450-$500 in 36 min | fraud | undocumented | 0.90 | $1,922.43 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-010 | structuring | C01890-K1 | 4 online txns $450-$500 in 27 min | fraud | undocumented | 0.90 | $1,921.59 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-011 | structuring | C00466-K1 | 4 online txns $450-$500 in 24 min | fraud | undocumented | 0.90 | $1,860.43 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-012 | structuring | C12897-K1 | 3 online txns $450-$500 in 10 min | fraud | undocumented | 0.98 | $1,999.89 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-013 | structuring | C05851-K1 | 4 online txns $450-$500 in 30 min | fraud | undocumented | 0.94 | $1,911.84 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-014 | structuring | C04697-K1 | 3 online txns $450-$500 in 5 min | fraud | undocumented | 0.90 | $1,499.85 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
| SEN-015 | structuring | C10751-K1 | 4 online txns $450-$500 in 21 min | fraud | undocumented | 0.90 | $1,906.11 | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2) |
