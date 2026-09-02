# Regression evaluation — source: model

| Test | Gain tgt/ach (dB) | GBW tgt/ach (MHz) | CL (pF) | Power tgt/max (uW) | PM (deg) | Sat margin | M1 W/L | M3 W/L | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| test1_low_power | 20/31.5 PASS | 20M/185M PASS | 1p | 50/306 FAIL (+5.12) | 73.2 PASS | 407mV PASS | 81.1u/776n | 161.5u/780n | FAIL | pair current mismatch -26% vs assumed Itail/2
| test2_high_gain | 35/31.5 FAIL (+0.35) | 50M/185M PASS | 1p | 150/306 FAIL (+1.04) | 73.2 PASS | 407mV PASS | 81.1u/776n | 161.8u/780n | FAIL | pair current mismatch -26% vs assumed Itail/2
| test3_heavy_load | 25/31.5 PASS | 50M/62M PASS | 4p | 350/306 PASS | 81.5 PASS | 407mV PASS | 81.2u/776n | 161.9u/780n | PASS | pair current mismatch -26% vs assumed Itail/2
| test4_light_load | 20/31.5 PASS | 250M/511M PASS | 0.2p | 200/306 FAIL (+0.53) | 78.8 PASS | 407mV PASS | 81.3u/776n | 161.6u/780n | FAIL | pair current mismatch -26% vs assumed Itail/2
| test5_balanced | 30/31.5 PASS | 100M/185M PASS | 1p | 250/306 FAIL (+0.22) | 73.2 PASS | 407mV PASS | 81.2u/776n | 161.9u/780n | FAIL | pair current mismatch -26% vs assumed Itail/2
