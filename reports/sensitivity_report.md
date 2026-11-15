# Sensitivity check

Calibrated score: 3.75 (lower = closer to ISRID). Each row changes ONE number; everything else stays calibrated. Tuned knobs: -50% / +50%. DATA values: -20% / +20%.

| Rule number | Kind | Score if lower | Score if higher | What moves most (lower) | What moves most (higher) |
|---|---|---|---|---|---|
| walk_sigma | tuned | 5.34 (+1.59) | 4.02 (+0.27) | field -3.0pts, dist_km_p25 +0.1 | same +3.1pts, dist_km_p25 -0.1 |
| p_spot | tuned | 5.19 (+1.44) | 4.45 (+0.70) | road -6.6pts, woods +3.7pts | road +5.1pts, track_offset_m_p50 -5.9 |
| p_struct | tuned | 5.12 (+1.37) | 4.14 (+0.39) | structure -6.5pts, woods +2.6pts | structure +5.8pts, woods -1.1pts |
| walk_median_min | tuned | 4.59 (+0.85) | 4.15 (+0.41) | woods +3.4pts, field +3.4pts | field -1.8pts, structure +1.5pts |
| p_cross_road | DATA | 4.24 (+0.49) | 4.46 (+0.72) | dispersion_deg_p50 +7.0, dist_km_p75 -0.3 | woods +1.9pts, dist_km_p75 +0.3 |
| speed_mean | DATA | 4.18 (+0.43) | 4.05 (+0.30) | same +1.6pts, downhill -1.5pts | road -1.9pts, structure +1.8pts |
| drain_tpi | tuned | 4.17 (+0.42) | 3.74 (-0.01) | drainage +4.7pts, woods -1.8pts | drainage -3.8pts, woods +2.7pts |
| p_drain | tuned | 3.94 (+0.19) | 4.14 (+0.40) | drainage -4.4pts, woods +2.9pts | drainage +3.2pts, downhill +1.0pts |
| share_direction | tuned | 4.11 (+0.36) | 3.76 (+0.01) | dist_km_p25 -0.1, same +2.2pts | structure +0.8pts, uphill +0.5pts |
| p_woods | tuned | 3.69 (-0.05) | 4.02 (+0.28) | structure +1.0pts, woods -0.8pts | woods +1.5pts, water -0.8pts |
| struct_min_m | tuned | 3.58 (-0.16) | 4.01 (+0.27) | structure +2.1pts, dist_km_p25 -0.0 | woods +1.2pts, structure -0.7pts |
| water_attract | tuned | 4.00 (+0.26) | 3.93 (+0.18) | woods +0.9pts, water -0.5pts | road +0.5pts, structure -0.4pts |
| road_stick | tuned | 3.95 (+0.21) | 3.95 (+0.20) | road -1.6pts, uphill +1.4pts | road +1.1pts, field -0.9pts |
| share_random | tuned | 3.79 (+0.05) | 3.94 (+0.20) | uphill +0.7pts, linear -0.5pts | dist_km_p25 -0.0, dist_km_p50 -0.1 |
| down_pref | tuned | 3.94 (+0.19) | 3.81 (+0.06) | uphill +0.9pts, downhill -0.8pts | structure +1.5pts, field -0.8pts |
| return_deg | tuned | 3.62 (-0.12) | 3.92 (+0.17) | dispersion_deg_p50 +2.7, downhill -1.0pts | structure +0.9pts, woods +0.8pts |
| up_avoid | tuned | 3.91 (+0.17) | 3.65 (-0.10) | woods +1.0pts, downhill -0.9pts | woods +0.4pts, road -0.4pts |
| wobble_direction | tuned | 3.91 (+0.16) | 3.75 (+0.00) | uphill +1.3pts, woods +1.1pts | linear -0.7pts, structure +0.6pts |
| p_brush | tuned | 3.85 (+0.11) | 3.77 (+0.02) | brush -1.7pts, uphill +1.1pts | brush +0.9pts, woods -0.7pts |
| p_water | tuned | 3.84 (+0.10) | 3.84 (+0.09) | structure -0.5pts, road +0.2pts | woods +1.0pts, structure -0.4pts |
| p_wet | tuned | 3.72 (-0.03) | 3.65 (-0.09) | same -0.4pts, structure +0.3pts | structure +0.6pts, road -0.6pts |
| p_stream | tuned | 3.82 (+0.07) | 3.73 (-0.01) | woods +0.9pts, water -0.5pts | water +0.4pts, brush -0.4pts |

Rules that matter most (score changes by 1 or more): walk_sigma, p_spot, p_struct.
Rules with little effect (under 0.3): p_woods, struct_min_m, water_attract, road_stick, share_random, down_pref, return_deg, up_avoid, wobble_direction, p_brush, p_water, p_wet, p_stream.

Run time 2 min.
