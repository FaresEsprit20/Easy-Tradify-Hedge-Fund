# Entry rule table on history (entry foundation v2)

Decisions: 107622 (2026-06-09 15:30 to 2026-09-15 18:45, halves split at 2026-07-30 07:00). Primary geometry: `precision|M15x1|1R`. Each cell: n (symbol-days) won% net R per decision, cluster-robust t.

## Baseline: every decision, its own side

| geometry | early half | later half |
|---|---|---|
| `engine` | n=53811 (588d) 14.7% -0.743R t=-47.7 | n=53811 (578d) 14.1% -0.800R t=-49.6 |
| `scalp|M5x1|1R` | n=53811 (588d) 41.5% -0.478R t=-55.5 | n=53811 (578d) 40.3% -0.516R t=-55.1 |
| `precision|M15x1|1R` | n=53811 (588d) 42.9% -0.322R t=-43.4 | n=53811 (578d) 41.6% -0.354R t=-42.8 |
| `precision|M15x1|2R` | n=53811 (588d) 29.2% -0.367R t=-34.5 | n=53811 (578d) 28.4% -0.398R t=-33.7 |
| `precision|H1x1|1R` | n=53811 (588d) 42.6% -0.207R t=-31.7 | n=53811 (578d) 42.0% -0.224R t=-31.1 |

## Each rule: passed vs failed (`precision|M15x1|1R`)

Lift = net R of passed minus failed. Other side = the same decisions traded the opposite way; a rule that lifts both sides is choosing conditions, not direction.

| rule | measured / passed | half | passed | failed | lift | lift other side |
|---|---|---|---|---|---|---|
| zone | 107622 / 107294 | early | n=53622 (588d) 43.0% -0.320R t=-43.1 | n=189 (147d) 15.9% -0.860R t=-15.6 | +0.540 | +0.379 |
|  |  | late | n=53672 (578d) 41.7% -0.353R t=-42.6 | n=139 (118d) 15.1% -0.872R t=-13.4 | +0.519 | +0.413 |
| signals | 107622 / 33777 | early | n=16804 (587d) 44.7% -0.277R t=-29.3 | n=37007 (588d) 42.1% -0.342R t=-39.7 | +0.065 | +0.078 |
|  |  | late | n=16973 (578d) 43.8% -0.313R t=-30.6 | n=36838 (578d) 40.6% -0.373R t=-40.0 | +0.061 | +0.065 |
| probability | 107622 / 9010 | early | n=4239 (387d) 46.5% -0.221R t=-10.1 | n=49572 (588d) 42.6% -0.331R t=-44.0 | +0.110 | +0.109 |
|  |  | late | n=4771 (396d) 43.8% -0.283R t=-13.4 | n=49040 (578d) 41.4% -0.361R t=-42.8 | +0.078 | +0.145 |
| discount | 107533 / 2829 | early | n=1419 (523d) 41.9% -0.370R t=-12.4 | n=52350 (588d) 43.0% -0.320R t=-43.3 | -0.050 | -0.026 |
|  |  | late | n=1410 (521d) 39.2% -0.413R t=-14.4 | n=52354 (578d) 41.7% -0.352R t=-42.4 | -0.060 | -0.016 |
| discount_quality | 107533 / 45835 | early | n=23146 (588d) 42.7% -0.329R t=-34.7 | n=30623 (587d) 43.1% -0.316R t=-39.2 | -0.013 | -0.030 |
|  |  | late | n=22689 (578d) 40.6% -0.374R t=-36.2 | n=31075 (578d) 42.3% -0.339R t=-37.5 | -0.035 | -0.025 |
| confirmation | 107622 / 51609 | early | n=25629 (588d) 42.9% -0.324R t=-36.8 | n=28182 (587d) 43.0% -0.320R t=-37.5 | -0.005 | +0.028 |
|  |  | late | n=25980 (578d) 41.6% -0.351R t=-35.6 | n=27831 (578d) 41.5% -0.357R t=-39.5 | +0.006 | +0.027 |
| timing | 0 / 0 | early | n=0 | n=0 | - | - |
|  |  | late | n=0 | n=0 | - | - |

## Entries under the current modes, and with one rule switched to observe

| modes | geometry | early half | later half |
|---|---|---|---|
| current | `engine` | n=2 (2d) 50.0% +0.269R t=+0.1 | n=1 (1d) 0.0% -1.526R t=- |
| current | `scalp|M5x1|1R` | n=2 (2d) 50.0% -0.243R t=-0.2 | n=1 (1d) 0.0% -1.827R t=- |
| current | `precision|M15x1|1R` | n=2 (2d) 100.0% +0.881R t=+9.0 | n=1 (1d) 0.0% -1.441R t=- |
| current | `precision|M15x1|2R` | n=2 (2d) 50.0% +0.381R t=+0.3 | n=1 (1d) 0.0% -1.441R t=- |
| current | `precision|H1x1|1R` | n=2 (2d) 50.0% -0.060R t=-0.1 | n=1 (1d) 0.0% -0.317R t=- |
| without zone | `precision|M15x1|1R` | n=2 (2d) 100.0% +0.881R t=+9.0 | n=3 (3d) 0.0% -1.241R t=-11.7 |
| without signals | `precision|M15x1|1R` | n=4 (4d) 50.0% -0.146R t=-0.2 | n=3 (3d) 33.3% -0.719R t=-1.2 |
| without probability | `precision|M15x1|1R` | n=7 (7d) 28.6% -0.723R t=-1.7 | n=10 (10d) 20.0% -0.874R t=-3.4 |
| without discount | `precision|M15x1|1R` | n=282 (178d) 50.7% -0.133R t=-2.3 | n=372 (220d) 47.6% -0.218R t=-4.0 |
| without discount_quality | `precision|M15x1|1R` | n=28 (24d) 46.4% -0.246R t=-1.4 | n=41 (36d) 36.6% -0.499R t=-3.5 |
| without confirmation | `precision|M15x1|1R` | n=3 (3d) 66.7% +0.174R t=+0.2 | n=2 (2d) 50.0% -0.382R t=-0.4 |
| without timing | `precision|M15x1|1R` | n=2 (2d) 100.0% +0.881R t=+9.0 | n=1 (1d) 0.0% -1.441R t=- |

## Verdict (rule fixed before the results were read)

| rule | current | verdict | lift early | lift later | why |
|---|---|---|---|---|---|
| zone | block | **observe** | +0.422 | +0.814 | unproven: smallest group 4 < 100 decisions |
| signals | block | **observe** | -0.011 | -0.024 | passed group does not beat failed group in both halves |
| probability | block | **block** | +0.110 | +0.078 | passed group beats failed group in both halves |
| discount | block | **observe** | -0.104 | -0.146 | passed group does not beat failed group in both halves |
| discount_quality | block | **block** | +0.050 | +0.049 | passed group beats failed group in both halves |
| confirmation | block | **observe** | +0.013 | -0.031 | passed group does not beat failed group in both halves |
| timing | block | **observe** | - | - | unproven: smallest group 0 < 100 decisions |

| entries under the verdict modes | early half | later half | pass line (later) | same entries, opposite side (later) |
|---|---|---|---|---|
| `engine` | n=1748 (335d) 17.2% -0.553R t=-9.3 | n=1892 (355d) 18.6% -0.523R t=-9.2 | fail | n=1892 (355d) 17.3% -0.600R t=-11.7 |
| `scalp|M5x1|1R` | n=1748 (335d) 44.8% -0.363R t=-11.6 | n=1892 (355d) 42.7% -0.423R t=-14.2 | fail | n=1892 (355d) 44.8% -0.389R t=-13.3 |
| `precision|M15x1|1R` | n=1748 (335d) 47.8% -0.191R t=-6.8 | n=1892 (355d) 45.2% -0.254R t=-9.3 | fail | n=1892 (355d) 47.5% -0.207R t=-7.7 |
| `precision|M15x1|2R` | n=1748 (335d) 34.4% -0.156R t=-3.6 | n=1892 (355d) 31.8% -0.253R t=-6.3 | fail | n=1892 (355d) 34.1% -0.191R t=-5.0 |
| `precision|H1x1|1R` | n=1748 (335d) 47.9% -0.085R t=-2.9 | n=1892 (355d) 47.4% -0.104R t=-3.8 | fail | n=1892 (355d) 45.9% -0.133R t=-4.9 |

## Probability band (chosen on the earlier half, checked on the later half)

- current 75-83 on the later half: n=1 (1d) 0.0% -1.441R t=-

## Winning setups the entry lets through (`precision|M15x1|1R`)

- current modes: 2 of 45474 winning decisions (0.0%)
- verdict modes: 1691 of 45474 winning decisions (3.7%)

## Per winning strategy group (verdict on that group's decisions only)

| group | decisions | rules that block | later half: entries | same, opposite side | all decisions (later) |
|---|---|---|---|---|---|
| CROSS_ASSET | 21449 | probability, confirmation | n=756 (164d) 43.6% -0.311R t=-8.1 | n=756 (164d) 49.7% -0.183R t=-4.8 | n=10725 (559d) 41.4% -0.358R t=-24.2 |
| MEAN_REVERSION | 33 | none | n=17 (3d) 64.7% +0.070R t=+0.4 | n=17 (3d) 29.4% -0.636R t=-5.4 | n=17 (3d) 64.7% +0.070R t=+0.4 |
| MOMENTUM | 25111 | discount_quality | n=5194 (590d) 40.4% -0.374R t=-21.3 | n=5194 (590d) 43.4% -0.315R t=-19.3 | n=12556 (594d) 41.6% -0.352R t=-27.4 |
| ORDER_FLOW | 863 | probability | n=105 (70d) 45.7% -0.225R t=-1.9 | n=105 (70d) 47.6% -0.182R t=-1.5 | n=432 (250d) 40.5% -0.354R t=-7.0 |
| TREND | 55973 | signals, probability, discount_quality, confirmation | n=172 (103d) 51.7% -0.090R t=-1.2 | n=172 (103d) 43.6% -0.252R t=-3.7 | n=27987 (578d) 41.6% -0.353R t=-32.5 |
| WAVE | 4193 | probability, discount_quality | n=233 (135d) 47.6% -0.261R t=-3.2 | n=233 (135d) 46.4% -0.292R t=-3.1 | n=2097 (448d) 42.6% -0.351R t=-12.3 |

## Entry status on history (first blocking rule)

- NO_POTENTIAL: 73614
- INSUFFICIENT_PROBABILITY: 30245
- WAITING_DISCOUNT: 3332
- INVALID_ZONE: 328
- POOR_DISCOUNT: 98
- CONFIRMED_DISCOUNT: 3
- WAITING_CONFIRMATION: 2
