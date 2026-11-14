# M4 · Threat model

Vizion is a Raspberry Pi 5 with a USB camera, LEDs/servo on GPIO, a dashboard on port 8765, an MQTT broker on 8883 and a Modbus link to a PLC. One threat per level, and the mitigations that are actually in this repository.

| Level | Threat | Impact | Mitigation in place | Where |
|---|---|---|---|---|
| **Device (physical)** | Someone unplugs or covers the camera, or swaps the SD card | False "present"/PASS, or a changed program | Camera loss or a frozen picture forces the safe state (LEDs off, NO VERDICT, `VISION_OK = 0`) within 3 s | `docs/M3_decision_rules.md`, `pi/dashboard.py` |
| **Network** | Anyone on the Wi-Fi reads or fakes detections and motor scores on MQTT | Spoofed PASS sent to the PLC, leaked production data | **Mitigation 1:** broker refuses connections without a password (`allow_anonymous false`), **TLS only** on 8883, no plain listener; per-user ACL (the PLC bridge uses the read-only `viewer` user) | `mqtt/mosquitto.conf`, `mqtt/acl`, `evidence/m4/mqtt_security_test_mac.txt` |
| **Application** | Requests to the dashboard API change state (turn detection off, quit) | Line stops or inspection is silently disabled | The dashboard listens on **127.0.0.1 only** by default; it is exposed (`--host 0.0.0.0`) only inside the container on a closed network. Static files are served from `web/` only (path traversal blocked in `Handler._file`) | `pi/dashboard.py` |
| **Data / model** | A bad update (wrong model, broken code) is installed | No detection, or wrong decisions | **Mitigation 2:** OTA updates install only tagged releases and **roll back automatically** if the health check (model ready within 90 s) fails | `pi/system/ota_update.sh` |
| **People / secrets** | Password committed to GitHub (the repo is public) | Anyone can join the broker | Passwords live only in `mqtt/passwd` and `docker/.env`, both git-ignored; services read them from environment variables | `.gitignore`, `pi/mqtt_link.py` |

**Two mitigations applied and tested:** (1) authenticated TLS MQTT: 4 of 4 security checks pass, `evidence/m4/mqtt_security_test_mac.txt`; (2) safe state on camera failure (LEDs off, PLC `VISION_OK = 0`), shown live and in `evidence/m4/plc_sim_tag_changes_mac.txt`.

**Left open (honest list):** the dashboard has no login (anyone on the Pi's screen can use it); the private CA key sits on the Pi; Modbus TCP itself has no authentication, so the PLC must be on a separate cable or VLAN.
