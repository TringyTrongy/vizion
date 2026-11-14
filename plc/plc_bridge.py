#!/usr/bin/env python3
"""PLC link: Vizion's detections (MQTT) -> PLC tags (Modbus TCP).

Subscribes to vizion/detections as the read-only MQTT user and writes the result into the PLC:

    coil 0             RESISTOR_PRESENT   (OpenPLC %QX100.0)
    coil 1             CAPACITOR_PRESENT  (%QX100.1)
    coil 2             KIT_PASS           (%QX100.2)
    coil 3             VISION_OK          (%QX100.3)  camera + model working; 0 = safe state
    holding reg 0      RESISTOR_COUNT     (%QW100)
    holding reg 1      CAPACITOR_COUNT    (%QW101)

A tag is written only when it changes, and every change is logged with the time it reached the
PLC, so the log shows "object detected -> PLC tag changed". If MQTT goes quiet for 3 s the bridge
clears VISION_OK and the presence coils (the PLC then treats the vision system as down).

    python plc_bridge.py --plc 127.0.0.1 --port 5020     # with plc_sim.py
    python plc_bridge.py --plc <openplc-ip> --port 502    # OpenPLC runtime

MQTT settings are the same environment variables as pi/mqtt_link.py (VIZION_MQTT_*), with
VIZION_MQTT_USER=viewer for read-only access.
"""
import argparse
import csv
import json
import os
import threading
import time
from pathlib import Path

COILS = ["RESISTOR_PRESENT", "CAPACITOR_PRESENT", "KIT_PASS", "VISION_OK"]
REGS = ["RESISTOR_COUNT", "CAPACITOR_COUNT"]
STALE_S = 3.0
SAFE = {"RESISTOR_PRESENT": False, "CAPACITOR_PRESENT": False, "KIT_PASS": False, "VISION_OK": False,
        "RESISTOR_COUNT": 0, "CAPACITOR_COUNT": 0}


def tags_from(msg):
    """vizion/detections payload -> {tag: value}. No counts (no picture) gives the safe state."""
    counts = msg.get("counts")
    ok = counts is not None and msg.get("camera") == "ok" and msg.get("model") == "ready"
    if not ok:
        return dict(SAFE)
    r, c = int(counts.get("resistor", 0)), int(counts.get("capacitor", 0))
    return {"RESISTOR_PRESENT": r > 0, "CAPACITOR_PRESENT": c > 0, "KIT_PASS": msg.get("verdict") == "PASS",
            "VISION_OK": True, "RESISTOR_COUNT": r, "CAPACITOR_COUNT": c}


class Plc:
    def __init__(self, host, port, unit, log_path):
        from pymodbus.client import ModbusTcpClient

        self.client = ModbusTcpClient(host, port=port)
        self.unit = unit
        self.current = {}
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.log_path.exists()
        self.log = self.log_path.open("a", newline="")
        self.csv = csv.writer(self.log)
        if new:
            self.csv.writerow(["wall_time", "tag", "value", "mqtt_to_plc_ms"])

    def _call(self, fn, address, value):
        try:
            return fn(address, value, device_id=self.unit)  # pymodbus >= 3.10
        except TypeError:
            return fn(address, value, slave=self.unit)

    def write(self, tags, received_t=None):
        if not self.client.connected and not self.client.connect():
            print("PLC not reachable, retrying", flush=True)
            return
        for tag, value in tags.items():
            if self.current.get(tag) == value:
                continue
            if tag in COILS:
                rr = self._call(self.client.write_coil, COILS.index(tag), bool(value))
            else:
                rr = self._call(self.client.write_register, REGS.index(tag), int(value))
            if rr.isError():
                print(f"PLC refused {tag}={value}: {rr}", flush=True)
                continue
            self.current[tag] = value
            ms = "" if received_t is None else round((time.monotonic() - received_t) * 1000, 1)
            self.csv.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), tag, int(value), ms])
            self.log.flush()
            print(f"PLC {tag} = {int(value)}  ({ms} ms after the MQTT message)", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plc", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--unit", type=int, default=1)
    ap.add_argument("--log", default=str(Path(__file__).resolve().parent / "logs" / "plc_bridge.csv"))
    args = ap.parse_args()

    import paho.mqtt.client as mqtt

    plc = Plc(args.plc, args.port, args.unit, args.log)
    lock = threading.Lock()
    last = {"t": time.monotonic()}

    def on_message(client, userdata, msg):
        t = time.monotonic()
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            return
        with lock:
            last["t"] = t
            plc.write(tags_from(payload), t)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"MQTT {reason_code}", flush=True)
        client.subscribe("vizion/detections", qos=1)

    env = os.environ
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="vizion-plc-bridge")
    c.username_pw_set(env.get("VIZION_MQTT_USER", "viewer"), env["VIZION_MQTT_PASSWORD"])
    c.tls_set(ca_certs=env.get("VIZION_MQTT_CAFILE", "/etc/mosquitto/certs/ca.crt"))
    c.on_connect, c.on_message = on_connect, on_message
    c.connect(env.get("VIZION_MQTT_HOST", "localhost"), int(env.get("VIZION_MQTT_PORT", "8883")))
    c.loop_start()
    try:
        while True:
            time.sleep(0.5)
            with lock:
                if time.monotonic() - last["t"] > STALE_S:
                    plc.write(SAFE)
    except KeyboardInterrupt:
        pass
    finally:
        c.loop_stop()
        plc.write(SAFE)


if __name__ == "__main__":
    main()
