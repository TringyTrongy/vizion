# PLC link (M4)

`plc_bridge.py` subscribes to `vizion/detections` (read-only MQTT user) and writes PLC tags over **Modbus TCP**. A tag is written only when it changes, and every change is logged.

| Modbus | Tag | OpenPLC address | Meaning |
|---|---|---|---|
| coil 0 | `RESISTOR_PRESENT` | `%QX100.0` | ≥ 1 resistor detected |
| coil 1 | `CAPACITOR_PRESENT` | `%QX100.1` | ≥ 1 capacitor detected |
| coil 2 | `KIT_PASS` | `%QX100.2` | the station verdict is PASS |
| coil 3 | `VISION_OK` | `%QX100.3` | camera + model working (0 = safe state, also after 3 s without MQTT) |
| holding reg 0 | `RESISTOR_COUNT` | `%QW100` | |
| holding reg 1 | `CAPACITOR_COUNT` | `%QW101` | |

```sh
pip install -r requirements.txt
python plc_sim.py --port 5020 &                         # a software PLC that logs every tag change
VIZION_MQTT_PASSWORD=... python plc_bridge.py --port 5020
```

With a real PLC, run the OpenPLC runtime (on the Pi or a PC), declare the tags above in its program, and point the bridge at it: `python plc_bridge.py --plc <ip> --port 502`.

## Measured (14 Nov 2026, Mac dry run)

`evidence/m4/plc_sim_tag_changes_mac.txt`: each time parts appeared or disappeared in the dashboard's test images, the PLC tags changed (e.g. `KIT_PASS 0 -> 1`, `RESISTOR_COUNT 0 -> 2`). `evidence/m4/plc_bridge_writes_mac.csv`: each write reached the PLC about 2 ms after the MQTT message.
