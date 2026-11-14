# Secure MQTT (M4)

Mosquitto on port **8883**, **TLS only**, **password required**, per-user topic rights (`acl`).

| File | What |
|---|---|
| `mosquitto.conf` | native broker config (→ `/etc/mosquitto/conf.d/vizion.conf`) |
| `mosquitto.docker.conf` | same, for `docker/docker-compose.yml` |
| `acl` | `vizion` may publish `vizion/#`; `viewer` may only read |
| `setup_broker.sh` | makes a private CA + server certificate, asks for the two passwords, installs and starts the broker |
| `test_security.sh` | the 4-check proof: no password → refused, wrong password → refused, no TLS → refused, password + TLS → works |

Generated files (`certs/`, `passwd`) are git-ignored, so no secret is ever in this public repository.

## Topics

| Topic | Publisher | Payload (JSON) |
|---|---|---|
| `vizion/detections` | `pi/dashboard.py` (on change + 1 Hz) | `counts`, `verdict` (PASS/FAIL/NO VERDICT), `reason`, `camera`, `model`, `ts` |
| `vizion/motor/score` | `pi/motor_monitor/motor_dashboard.py` (1 Hz, retained) | `state`, `mismatch`, `limit`, `fps`, `anomalies`, `ts` |
| `vizion/status` | dashboard | `online` / `offline` (retained, last will) |

Subscribe: `mosquitto_sub -h <pi> -p 8883 --cafile certs/ca.crt -u viewer -P <password> -t 'vizion/#' -v`

## Measured

- `evidence/m4/mqtt_security_test_mac.txt`: all 4 checks passed (Mosquitto 2.0 on the Mac, same config and scripts; 14 Nov 2026).
- `evidence/m4/mqtt_topics_subscriber_mac.txt`: both topics received over TLS while the dashboard and the motor monitor (simulated rig) ran.
