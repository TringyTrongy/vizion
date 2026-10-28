# Edge AI C7: evidence index

Viswes Vijayaragavan Sivakumar, 24BCS321. This maps the tasks of the C7 individual assessment (M1 6, M2 6, M3 6, M4 8, M5 8) to what this repository actually contains. Where there is no evidence the entry says so. Nothing here was measured after 10 October 2026; every number comes from the READMEs, which record the Pi runs.

**Scope note.** Vizion detects resistors and capacitors. The C7 brief asks for the IDRP part (CAD and printed) as the detected objects. That work is in a separate repository, `edge-ai-c7` (detector trained and exported to ONNX on a PC). The IDRP part has not been printed, so nothing in either repository was run on the Pi against it.

Status: **Yes** = evidence exists in this repo. **Partly** = something related exists but does not meet the task as written. **No** = nothing yet.

## M1 Detect

| Task | Status | Evidence |
|---|---|---|
| Camera and first commit with spec sheet and first frame | Partly | `capture_20261006_*.jpg` (first frames, 610x480); camera and Pi 5 spec in `pi/README.md`. No separate spec sheet |
| OpenCV pipeline with live overlay on the device | Yes | `pi/dashboard.py`, `pi/detector.py`, `docs/dashboard.jpg`, `model/live_detection.png` |
| Baseline FPS, latency, CPU/GPU load, temperature | Partly | About 41 ms per frame (4 cores) and 49-57 ms (3 cores) in `model/README.md`; webcam 15 fps, about 8 fps in dim light; Pi about 75 C without a fan (`pi/README.md`). No CPU-load figure, no baseline table |
| Dataset v1, labelled | Yes | `data/` (2197 images, 2 classes), sources in `data/README.md` |
| Correct 70/20/10 split | No | Actual split is 1779 / 307 / 111 (about 81 / 14 / 5) |
| Train and run detector: mAP, P, R, confusion matrix, 10 wrong detections explained | Partly | mAP50 0.938 at 480, `model/training/confusion_matrix_normalized.png`, `results.csv`. No write-up of 10 wrong detections |

## M2 Optimize

| Task | Status | Evidence |
|---|---|---|
| ONNX export | No | Model is exported to NCNN only (`model/vizion_ncnn_model`) |
| TFLite INT8 or TensorRT on the device | No | NCNN FP on CPU |
| Accuracy (mAP) before and after | No | Only the colour-balance before/after in `model/README.md` |
| Fair benchmark (20 warm-up, 100+ timed, median/p95, FPS, size) | No | Single timing figures only |
| CPU vs accelerator table and software stack | No | Pi 5 has no accelerator in use; stack is listed in `pi/README.md` |
| Own target and trade-off written before training | No | |

## M3 Decide and Act

| Task | Status | Evidence |
|---|---|---|
| Decision rule sheet | Partly | LED rules in `pi/README.md`, `pi/leds.py` |
| Two-stream pipeline | No | Detector runs in a separate process, not a two-stream design |
| Debounce | Yes | `pi/tracker.py`, `pi/test_tracker.py`; motor monitor trips after 3 frames in a row |
| Actuator fires | Yes | LEDs on GPIO17/27 (`pi/leds.py`); servo fan and motor stop (`pi/sensor_monitor/fan_control.py`, `pi/motor_monitor/motor_watch.py`) |
| Docker cold boot | No | Autostart is through `.desktop` launchers, not Docker |
| End-to-end latency over 20+ events | No | |

## M4 Monitor and Connect

| Task | Status | Evidence |
|---|---|---|
| MPU6050 normal and fault CSVs | No | Sensor is a DHT11; motor is watched by the camera. Logs are CSV (`pi/sensor_monitor/export_csv.py`) |
| Anomaly model | Partly | Rule-based detector on DHT11, evaluated on NAB data (`pi/sensor_monitor/reports/nab_evaluation.md`); camera-based motor anomaly (`pi/motor_monitor/`), 273 master images, hold test scored 0.83-1.19 vs 0.01-0.03 normal |
| False alarms over 5 normal runs | No | |
| Secure MQTT (refused without password, works with password + TLS) | No | |
| Topics | No | |
| PLC link | No | |
| Threat model | No | |
| Reliability: drift report, OTA v1 to v2 with rollback, auto-restart | Partly | Autostart launchers and safety shutdowns only |

## M5 Complete System and Dashboard

| Task | Status | Evidence |
|---|---|---|
| Inspection rig | Partly | Pi, camera and servo rig; not an IDRP inspection rig |
| Pass/fail station (20 parts) | No | |
| Full chain, 10 minutes | No | |
| Live dashboard with 3 KPIs | Yes | `pi/web/`, `docs/*.jpg` |
| Product readiness: auto-start, offline, logs | Yes | `pi/vizion-*.desktop`, CSV logs, runs without internet |
| Headline metric | No | |
| Documents | Partly | READMEs, `PRODUCT.md`, `DESIGN.md`, model card |
| Live demo | No | Not yet run on the IDRP part |

## Totals

Of the 34 tasks listed above: 6 Yes, 8 Partly, 20 No.

## Tests that run without hardware

`pi/test_tracker.py`, `test_dashboard_logic.py`, `test_leds.py`, `test_detector.py` and `pi/motor_monitor/test_motor_monitor.py` (20 tests) passed on 28 October 2026.
