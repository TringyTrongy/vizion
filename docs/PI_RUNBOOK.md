# Pi runbook: collect every measured number in one session (about 90 minutes)

Everything here is code that is already in the repo; this session only produces the numbers. After each step, copy the file named in **Save** into `evidence/` and commit it.

Setup once: `cd ~/vizion-repo && git pull`, then `cp -r pi/* ~/vizion/` (or use `pi/system/ota_update.sh`), and `~/vizion/.venv/bin/pip install paho-mqtt smbus2 "pymodbus==3.8.6"`.

## M3 Decide and Act

| # | Do | Save |
|---|---|---|
| 1 | Start the dashboard (`./run_dashboard.sh`), place and remove parts **25+ times**. Then `python latency_log.py logs/latency.csv` | `logs/latency.csv` + the printed median/p95 → `evidence/m3/latency_pi.csv`, `evidence/m3/latency_pi.txt` |
| 2 | Two streams: plug in a 2nd USB camera (or use a folder) and run `python two_stream.py --a /dev/video0 --b /dev/video2 --seconds 60` | `logs/two_stream.csv` → `evidence/m3/two_stream_pi.csv` |
| 3 | Docker: `sudo apt install docker.io docker-compose-plugin`, `sudo usermod -aG docker $USER`, then `docker compose -f docker/docker-compose.yml up -d --build`. Unplug the Pi's power, plug it back in, start a stopwatch: time until the LED lights for a part on the table | Photo/video + `docker ps` output → `evidence/m3/docker_cold_boot.md` |
| 4 | Safe state: pull the camera USB with LEDs on | short video → `evidence/m3/safe_state.mp4` (or a link to it) |

## M4 Monitor and Connect

| # | Do | Save |
|---|---|---|
| 5 | MQTT: `sudo mqtt/setup_broker.sh`, then `VIZION_MQTT_PASSWORD=… mqtt/test_security.sh` | output → `evidence/m4/mqtt_security_test_pi.txt` |
| 6 | Topics: put `VIZION_MQTT_PASSWORD=…` in `~/.config/vizion/env`, restart, then `mosquitto_sub -h localhost -p 8883 --cafile mqtt/certs/ca.crt -u viewer -P … -t 'vizion/#' -v` | screenshot → `evidence/m4/topics_pi.png` |
| 7 | MPU6050: wire it (see `pi/mpu6050/mpu_logger.py`), record `normal 1-3` and `fault 1-3` (60 s each), then 5 more normal runs `check_normal_1-5` | `pi/mpu6050/data/*.csv` → commit them |
| 8 | `python mpu_anomaly.py train data/normal_{1,2,3}.csv`, `evaluate data/*.csv`, `false-alarms data/check_normal_*.csv`, and `live` while you shake the motor | outputs → `evidence/m4/mpu_anomaly_pi.txt` |
| 9 | Motor false alarms: run Vizion Motor 5 times for 5 min each with no fault; count ANOMALY trips in `pi/motor_monitor/data/log/` | `evidence/m4/motor_false_alarms.md` |
| 10 | PLC: `python plc/plc_sim.py` (or OpenPLC) + `python plc/plc_bridge.py`; put a part down | `plc/logs/plc_tags.csv` → `evidence/m4/plc_pi.csv` |
| 11 | Reliability: install `pi/system/vizion-dashboard.service`, run `pi/system/crash_test.sh 5`; then `ota_update.sh v1`, `v2`, `v2-bad` | `logs/crash_test.csv`, `~/vizion-releases/ota.log` → `evidence/m4/` |

## M5 Complete System

| # | Do | Save |
|---|---|---|
| 12 | Rig: fix the camera on a stand at a measured height, lamp on, and photograph it | `evidence/m5/rig.jpg` |
| 13 | Pass/fail: 20 trays (10 correct kits of 2R+2C, 10 defective: missing/extra/wrong part, unknown object). For each, press GOOD or DEFECTIVE on `/station` | `logs/station.csv` + a screenshot of the matrix → `evidence/m5/` |
| 14 | Full chain: run everything for **10 minutes** with `--stats`, note anything that breaks and the fix | `dashboard.log` → `evidence/m5/full_chain_10min.log` |
| 15 | Product readiness: power-cycle with the network cable out; the station page must come up by itself | video → `evidence/m5/power_cycle.mp4` |
