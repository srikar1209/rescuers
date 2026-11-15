# Calibration report

20 random start points in Amherst, 400 walkers each per setting; 400 settings searched with Bayesian optimization (Optuna TPE); top 5 re-tested with 1,500 walkers per start and new seeds, best kept. Run time 19 min.

## ISRID target vs model

| Statistic | ISRID | Before | After |
| --- | --- | --- | --- |
| dist_km_p25 | 0.3 | 0.2 | 0.4 |
| dist_km_p50 | 1.0 | 0.4 | 1.0 |
| dist_km_p75 | 2.4 | 0.8 | 2.5 |
| structure | 20 | 26.6 | 18.9 |
| road | 18 | 6.3 | 18.7 |
| woods | 17 | 28.6 | 24.5 |
| field | 14 | 12.3 | 10.5 |
| linear | 9 | 3.0 | 6.8 |
| drainage | 9 | 4.2 | 13.3 |
| water | 7 | 17.8 | 3.5 |
| brush | 6 | 1.2 | 3.9 |
| track_offset_m_p50 | 15 | 22.4 | 20.0 |
| dispersion_deg_p50 | 23 | 14.8 | 8.1 |
| downhill | 42 | 40.0 | 39.0 |
| same | 39 | 42.3 | 28.8 |
| uphill | 19 | 17.7 | 32.2 |

Score (lower is better): before 9.91, after 3.83

Stability: two runs of 20,000 walkers with different seeds share 56% of their hot zone (80% probability area).

## Tuned values (ASSUMPTIONS)

| Knob | Default | Calibrated |
| --- | --- | --- |
| share_direction | 0.6 | 0.8333 |
| share_random | 0.25 | 0.118 |
| wobble_direction | 10 | 7.715 |
| down_pref | 0.3 | 0.1109 |
| up_avoid | 0.3 | 0.1752 |
| p_struct | 0.3 | 0.08567 |
| p_water | 0.8 | 0.01193 (at LOW limit) |
| p_stream | 0.05 | 0.001703 |
| water_attract | 1.5 | 1.043 (at LOW limit) |
| p_wet | 0.01 | 0.0002712 |
| p_brush | 0.02 | 0.04215 (at HIGH limit) |
| p_woods | 0.002 | 0.0003023 |
| p_drain | 0.005 | 0.006295 |
| road_stick | 8 | 2.96 |
| drain_tpi | -1 | -1.178 |
| struct_min_m | 50 | 109.2 |
| return_deg | 10 | 6.629 |
| p_spot | 0.02 | 0.06217 |
| walk_median_min | 90 | 322.7 |
| walk_sigma | 1.2 | 1.596 |

## Why walkers stopped (after calibration)

| Reason | Share |
| --- | --- |
| stuck in terrain | 20.8% |
| stopped at building | 18.9% |
| in water | 1.0% |
| mobility time over | 30.3% |
| left map | 6.9% |
| simulation time over | 1.4% |
| spotted by public | 20.7% |

## Where woods finds come from

| Map class | Share of all finds |
| --- | --- |
| forest | 17.2% |
| wetland | 7.3% |

## Remaining error by statistic (largest first)

| Statistic | Share of remaining error |
| --- | --- |
| woods | 20% |
| water | 14% |
| drainage | 11% |
| field | 9% |
| uphill | 9% |
| same | 7% |

DATA values (speed, 66% road crossing) were not tuned. ISRID's two samples disagree: mobility hours (n = 42) are far more spread out than distances (n = 175). Walking time is a lognormal (`walk_median_min`, `walk_sigma`) tuned to the larger distance sample. 'Same elevation' = within +/-5 m (2 m is inside elevation map noise).