# Evidence index: M3, M4, M5

One section per task on the assessment sheet. Each says what was built, where the code is, the **measured numbers**, and where they were measured:

- **Pi**: measured on the Raspberry Pi 5 rig (October 2026, numbers from the READMEs).
- **Mac dry run**: the same code run on a Mac on 14 Nov 2026, with the real model on the real webcam frames from `data/webcam/raw` instead of the live camera, pretend LEDs (`--sim-leds`), a real Mosquitto broker and a simulated PLC/motor. It proves the code works end to end; the Pi numbers come from `docs/PI_RUNBOOK.md`.
- **Pi run pending**: code is ready, the number still has to be taken on the Pi (runbook step given).

## M3 Decide and Act

### M3 Decision rule sheet
[`docs/M3_decision_rules.md`](../docs/M3_decision_rules.md): six rules (input → threshold → debounce → action) and the safe state for every failure: camera lost or frozen for 3 s → both LEDs off, NO VERDICT, PLC `VISION_OK = 0`.

### M3 Two-stream pipeline
[`pi/two_stream.py`](../pi/two_stream.py): two sources, one reader thread and one NCNN detector process each.
**Mac dry run** ([`m3/two_stream_mac_dryrun.csv`](m3/two_stream_mac_dryrun.csv)): stream A 15.1 fps video / 14.9 fps detected (9.7 ms per frame), stream B 15.1 / 14.8 fps (17.5 ms), at the same time, over 15 s. **Pi run pending** (runbook step 2).

### M3 Debounce
[`pi/tracker.py`](../pi/tracker.py): a part is shown only after **2 frames** above 0.25 (1 frame if ≥ 0.60), and hidden after 5 misses or below 0.15. Tested by [`pi/test_tracker.py`](../pi/test_tracker.py) (`test_single_frame_false_positive_not_shown`, 7/7 pass). Vizion Motor stops only after **3 frames in a row** over the limit; the MPU6050 alert after 3 windows in a row ([`pi/mpu6050/test_mpu_anomaly.py`](../pi/mpu6050/test_mpu_anomaly.py): a 0.1 s knock does not alert).

### M3 Actuator fires
[`pi/leds.py`](../pi/leds.py): red LED D1 on GPIO17 (pin 11) for resistors, yellow D2 on GPIO27 (pin 13) for capacitors. **Pi**: [`docs/dashboard.jpg`](../docs/dashboard.jpg). The servo motor stop is in [`pi/motor_monitor/`](../pi/motor_monitor).

### M3 Docker
[`docker/Dockerfile`](../docker/Dockerfile), [`docker/docker-compose.yml`](../docker/docker-compose.yml), [`docker/README.md`](../docker/README.md): non-root container with camera + GPIO devices, health check, `restart: unless-stopped` next to the MQTT broker, so it comes back after a power cut. **Pi run pending** (runbook step 3: cold boot, time to LED on).

### M3 End-to-end latency
[`pi/latency_log.py`](../pi/latency_log.py) + the hook in `pi/dashboard.py`: one CSV row per LED change, time from the camera frame to the GPIO write.
**Mac dry run** ([`m3/latency_mac_dryrun.csv`](m3/latency_mac_dryrun.csv)): **810 events, median 83.1 ms, p95 98.7 ms, max 143.3 ms**. **Pi run pending** (runbook step 1).

## M4 Monitor and Connect

### M4 Sensor data
[`pi/mpu6050/mpu_logger.py`](../pi/mpu6050/mpu_logger.py): MPU6050 over I²C at 100 Hz, labelled `normal_N.csv` / `fault_N.csv`. **Pi run pending** (runbook step 7). The existing DHT11 logging and CSV export are in [`pi/sensor_monitor/`](../pi/sensor_monitor).

### M4 Anomaly model
[`pi/mpu6050/mpu_anomaly.py`](../pi/mpu6050/mpu_anomaly.py): trained on **normal data only**, threshold = normal p99.5 × 1.5, live `ALERT` mode.
**Pi** (camera-based, [`pi/motor_monitor/README.md`](../pi/motor_monitor/README.md)): a held arm scored 0.83–1.19 against 0.01–0.03 for normal movement. **Mac dry run** (simulated rig): holding the arm gave `ANOMALY` with mismatch 0.90 against a limit of 0.15, and the alert reached the station page over MQTT ([`m5/station_motor_alert_mac_dryrun.jpg`](m5/station_motor_alert_mac_dryrun.jpg)).

### M4 False alarms
**Pi**: the DHT11 rule detector on the public NAB data: [`pi/sensor_monitor/reports/nab_evaluation.md`](../pi/sensor_monitor/reports/nab_evaluation.md). Threshold reasoning: [`docs/M3_decision_rules.md`](../docs/M3_decision_rules.md) (R5, R6). `python mpu_anomaly.py false-alarms` counts alerts over 5 unseen normal runs. **Pi run pending** (runbook steps 8–9).

### M4 Secure MQTT
[`mqtt/`](../mqtt): TLS-only Mosquitto on 8883, `allow_anonymous false`, password file, ACL.
**Mac dry run** ([`m4/mqtt_security_test_mac.txt`](m4/mqtt_security_test_mac.txt)): **4 of 4 checks passed**. No password → *refused: not authorised*; wrong password → refused; no TLS → protocol error; password + TLS → message received.

### M4 Topics
`vizion/detections` from [`pi/mqtt_link.py`](../pi/mqtt_link.py), and `vizion/motor/score` from Vizion Motor. **Mac dry run** ([`m4/mqtt_topics_subscriber_mac.txt`](m4/mqtt_topics_subscriber_mac.txt)): both received on a TLS subscriber.

### M4 PLC link
[`plc/plc_bridge.py`](../plc/plc_bridge.py) (MQTT → Modbus TCP tags) and [`plc/plc_sim.py`](../plc/plc_sim.py), a software PLC. **Mac dry run** ([`m4/plc_sim_tag_changes_mac.txt`](m4/plc_sim_tag_changes_mac.txt)): tags flip as parts appear, e.g. `KIT_PASS 0 -> 1`, `RESISTOR_COUNT 0 -> 2`, about 2 ms after the MQTT message ([`m4/plc_bridge_writes_mac.csv`](m4/plc_bridge_writes_mac.csv)).

### M4 Threat model
[`docs/M4_threat_model.md`](../docs/M4_threat_model.md): one threat per level and two tested mitigations.

### M4 Reliability
- **Drift report:** [`m4/drift_report_webcam_oct6_vs_oct7.md`](m4/drift_report_webcam_oct6_vs_oct7.md), from [`pi/drift_report.py`](../pi/drift_report.py) on the real webcam frames. The inputs drifted (sharpness +997%); detector confidence held at 0.841 → 0.835.
- **OTA v1 → v2 with rollback:** [`pi/system/ota_update.sh`](../pi/system/ota_update.sh).
- **Auto-restart after a crash:** [`pi/system/vizion-dashboard.service`](../pi/system/vizion-dashboard.service) + [`pi/system/crash_test.sh`](../pi/system/crash_test.sh).
- **Pi run pending** for OTA and crash timing (runbook step 11).

## M5 Complete System

### M5 Inspection rig
**Pi**: [`model/live_detection.png`](../model/live_detection.png), all four parts found at 80–90%. **Pi run pending**: a photo of the fixed camera and lamp (runbook step 12).

### M5 Pass/fail station
[`pi/station.py`](../pi/station.py) + [`pi/web/station.html`](../pi/web/station.html): PASS only if the kit matches and nothing unrecognised is present. GOOD/DEFECTIVE labels feed a live confusion matrix and false-pass rate. **Pi run pending**: 10 good + 10 defective trays (runbook step 13).

### M5 Full chain on the device
**Mac dry run** ([`m5/full_chain_10min_mac.log`](m5/full_chain_10min_mac.log)): camera source → detector → tracker → LEDs → station page → MQTT → PLC, running together for 10 minutes. CHAIN_SUMMARY

### M5 Live dashboard
`/station`: live camera with boxes, PASS/FAIL, 3 KPIs, headline metric, motor alert ([`m5/station_pass_mac_dryrun.jpg`](m5/station_pass_mac_dryrun.jpg), [`m5/station_motor_alert_mac_dryrun.jpg`](m5/station_motor_alert_mac_dryrun.jpg)). The original Pi dashboard: [`docs/dashboard.jpg`](../docs/dashboard.jpg).

### M5 Product readiness
Auto-start: [`pi/system/vizion-dashboard.service`](../pi/system/vizion-dashboard.service) + [`pi/system/vizion-kiosk.desktop`](../pi/system/vizion-kiosk.desktop) (or Docker). Runs offline. Logs: `dashboard.log`, `logs/*.csv`. **Pi run pending**: power-cycle demo (runbook step 15).

### M5 Headline metric
**Pi** ([`model/README.md`](../model/README.md#results)): **52 of 52 parts found, 0 false boxes** on 15 hand-labelled webcam frames; mAP50 0.938. Live: correct verdicts out of N on the station page.

### M5 Documents
[`README.md`](../README.md), [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md), [`model/README.md`](../model/README.md), [`docs/PI_RUNBOOK.md`](../docs/PI_RUNBOOK.md).
