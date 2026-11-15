# Benchmark

999 cases in Amherst, start points held out from calibration. True spots placed with ISRID statistics only (not by our walkers). Score = area searched before reaching the truth, most likely cells first.

## Test A: no clues

| Method | Median km2 | Found within 0.25 km2 | Found within 0.5 km2 | Found within 1 km2 | Found within 2 km2 |
|---|---|---|---|---|---|
| Rings around last seen (basic instinct) | 3.16 | 21% | 27% | 35% | 43% |
| ISRID stats map (ceiling: same recipe as the truths) | 0.92 | 36% | 44% | 51% | 58% |
| Our model, no clues | 2.19 | 26% | 33% | 40% | 49% |

Our model vs rings: 546 wins, 48 ties, 405 losses (wins 57% of the cases that are not ties). Median per case: 1.2x less area. Total area over all cases: rings 23126 km2, our model 19381 km2.
(Tie = both reach the person within 0.05 km2.)

### By distance of the truth

| Distance | Cases | Rings median km2 | Our model median km2 | Wins | Ties | Losses |
|---|---|---|---|---|---|---|
| < 0.5 km | 324 | 0.16 | 0.10 | 153 | 48 | 123 |
| 0.5-1.5 km | 270 | 2.47 | 1.74 | 175 | 0 | 95 |
| 1.5-3 km | 148 | 13.44 | 6.63 | 106 | 0 | 42 |
| > 3 km | 257 | 85.63 | 65.21 | 112 | 0 | 145 |

### By find type

| Type | Cases | Rings median km2 | Our model median km2 |
|---|---|---|---|
| water | 65 | 4.15 | 2.14 |
| road | 198 | 2.53 | 2.43 |
| linear | 83 | 3.25 | 2.00 |
| structure | 214 | 2.47 | 1.63 |
| drainage | 81 | 5.22 | 1.92 |
| brush | 30 | 18.24 | 2.76 |
| woods | 174 | 3.56 | 2.81 |
| field | 154 | 2.19 | 2.70 |

## Test B: one sighting

954 cases with a sighting.

| Method | Median km2 | Found within 0.25 km2 | Found within 0.5 km2 | Found within 1 km2 | Found within 2 km2 |
|---|---|---|---|---|---|
| Rings around the sighting | 0.97 | 32% | 40% | 50% | 59% |
| Our model + sighting, reweight only (old) | 0.36 | 44% | 54% | 61% | 66% |
| Our model + sighting, restart from sighting | 0.35 | 44% | 55% | 65% | 75% |

Our model vs rings around the sighting: 721 wins, 83 ties, 150 losses (wins 83% of the cases that are not ties). Median per case: 2.7x less area. Total area over all cases: rings around the sighting 6611 km2, our model 2928 km2.

### By distance of the truth

| Distance | Cases | Rings around sighting median km2 | Our model median km2 | Wins | Ties | Losses |
|---|---|---|---|---|---|---|
| < 0.5 km | 285 | 0.06 | 0.05 | 119 | 81 | 85 |
| 0.5-1.5 km | 269 | 0.66 | 0.24 | 239 | 2 | 28 |
| 1.5-3 km | 146 | 3.37 | 1.06 | 138 | 0 | 8 |
| > 3 km | 254 | 20.09 | 4.41 | 225 | 0 | 29 |

Run time 59 min. Slowest cases: #527 381 s (start [599, 584]), #525 381 s (start [575, 333]), #526 380 s (start [1578, 491])
