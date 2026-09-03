# Surrogate failure taxonomy (Phase B)

Unresolved requests analyzed: **220**

## By dominant constraint

| Category | Failures |
|---|---|
| Power_max | 157 |
| GBW_min | 55 |
| Gain_min | 6 |
| W_nmos_max | 1 |
| W_pmos_max | 1 |

## By gain bin

| Category | Failures |
|---|---|
| 30-35dB | 131 |
| 25-30dB | 71 |
| <25dB | 13 |
| 35-40dB | 5 |

## By gbw bin

| Category | Failures |
|---|---|
| <20MHz | 69 |
| 50-100MHz | 46 |
| 20-50MHz | 41 |
| 100-200MHz | 31 |
| >=400MHz | 20 |
| 200-400MHz | 13 |

## By cl bin

| Category | Failures |
|---|---|
| >=4pF | 92 |
| 0.5-2pF | 65 |
| <0.5pF | 63 |

## By power bin

| Category | Failures |
|---|---|
| <50uW | 132 |
| >=300uW | 37 |
| 50-150uW | 27 |
| 150-300uW | 24 |

## Support and structure

- within train support (nn dist < 0.05): 218
- outside train support: 2
- all heads evaluate invalid: 0
- at least one head passes hard verify (selection failure): 0
- median pairwise head distance: 0.540

