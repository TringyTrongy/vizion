# Drift report (2026-11-14 17:44)

Baseline: `data/webcam/raw/capture_20261006_*` (3 frames) · Recent: `data/webcam/raw/capture_20261007_*` (12 frames)

| Statistic | Baseline mean | Recent mean | Change | PSI | Verdict |
|---|---|---|---|---|---|
| brightness | 149.815 | 163.336 | +9.0% | 6.984 | DRIFTED |
| contrast | 27.650 | 58.738 | +112.4% | 6.139 | DRIFTED |
| r_over_g | 1.017 | 0.996 | -2.0% | 6.984 | DRIFTED |
| b_over_g | 0.973 | 1.048 | +7.7% | 6.139 | DRIFTED |
| sharpness | 195.934 | 2149.825 | +997.2% | 6.139 | DRIFTED |

| Detector | Baseline | Recent |
|---|---|---|
| parts per frame (mean) | 1.33 | 4.00 |
| mean confidence | 0.841 | 0.835 |
| confidence PSI | 5.142 | |

**Overall: DRIFTED** (largest input PSI 6.984). PSI < 0.1 stable, 0.1-0.25 watch, > 0.25 drifted: re-learn the empty table, check the light, and retrain if the detector's confidence fell.

## Reading this report

Measured on the Mac, 14 Nov 2026, with `pi/drift_report.py` on the real webcam frames in this repo (first captures on 6 Oct vs the scenes captured on 7 Oct).

- The **inputs drifted**: 7 Oct frames are much sharper (+997%) and higher-contrast (+112%), and the scenes changed (single parts on 6 Oct, 4-part layouts on 7 Oct). The script flags this correctly; check focus and lighting when it does. The PSI values are inflated because the baseline has only 3 frames; with a proper baseline (100+ frames from the first day of a run) PSI is meaningful on its own.
- The **detector did not drift**: mean confidence 0.841 → 0.835 (−0.7%), so the model still sees parts as well after the change. Action from this report: re-learn the empty table after moving the camera; no retraining needed.
