# Regression evaluation — source: model_solved

| Test | Gain tgt/ach (dB) | GBW tgt/ach (MHz) | CL (pF) | Power tgt/max (uW) | PM (deg) | Sat margin | M1 W/L | M3 W/L | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| test1_low_power | 20/31.9 PASS | 20M/202M PASS | 1p | 50/306 FAIL (+5.12) | 73.2 PASS | 408mV PASS | 81.0u/776n | 161.5u/780n | FAIL |
| test2_high_gain | 35/31.9 FAIL (+0.31) | 50M/202M PASS | 1p | 150/306 FAIL (+1.04) | 73.2 PASS | 408mV PASS | 81.0u/776n | 161.7u/780n | FAIL |
| test3_heavy_load | 25/31.9 PASS | 50M/69M PASS | 4p | 350/306 PASS | 80.7 PASS | 408mV PASS | 81.0u/776n | 161.9u/780n | PASS |
| test4_light_load | 20/31.9 PASS | 250M/568M PASS | 0.2p | 200/306 FAIL (+0.53) | 79.4 PASS | 408mV PASS | 81.2u/776n | 161.5u/780n | FAIL |
| test5_balanced | 30/31.9 PASS | 100M/202M PASS | 1p | 250/306 FAIL (+0.22) | 73.2 PASS | 408mV PASS | 81.1u/776n | 161.9u/780n | FAIL |
