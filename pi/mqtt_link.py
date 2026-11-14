"""Optional MQTT link: publishes Vizion's results to the Mosquitto broker over TLS with a password.

Topics (all JSON, QoS 1):
    vizion/detections     {"counts": {...}, "verdict": "PASS", "reason": ..., "fps": ..., "ts": ...}
                          on every change and once a second as a heartbeat
    vizion/motor/score    {"state": "RUNNING", "mismatch": 0.02, "limit": 0.4, "ts": ...}  (motor_dashboard.py)
    vizion/status         "online" / "offline" (retained; "offline" is the broker's last will)

The connection settings come from environment variables, so no password is ever in the repo:
    VIZION_MQTT_HOST (default localhost)   VIZION_MQTT_PORT (default 8883)
    VIZION_MQTT_USER (default vizion)      VIZION_MQTT_PASSWORD   (required)
    VIZION_MQTT_CAFILE (default /etc/mosquitto/certs/ca.crt)
Without VIZION_MQTT_PASSWORD, or without paho-mqtt installed, the link stays off and Vizion runs
as before. Setup: ../mqtt/README.md.
"""
import json
import os
import threading
import time


class MqttLink:
    def __init__(self, client_id="vizion", env=os.environ, client_factory=None):
        self.enabled, self.detail, self.connected = False, "off (no VIZION_MQTT_PASSWORD)", False
        self.client = None
        self._last = {}
        self._lock = threading.Lock()
        self.subscriptions = {}  # topic -> latest decoded payload
        password = env.get("VIZION_MQTT_PASSWORD")
        if not password:
            return
        try:
            if client_factory is None:
                import paho.mqtt.client as mqtt

                def client_factory(cid):
                    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
            c = client_factory(client_id)
            c.username_pw_set(env.get("VIZION_MQTT_USER", "vizion"), password)
            cafile = env.get("VIZION_MQTT_CAFILE", "/etc/mosquitto/certs/ca.crt")
            if cafile and cafile.lower() != "none":
                c.tls_set(ca_certs=cafile)
            c.will_set("vizion/status", "offline", qos=1, retain=True)
            c.on_connect = self._on_connect
            c.on_disconnect = self._on_disconnect
            c.on_message = self._on_message
            c.connect_async(env.get("VIZION_MQTT_HOST", "localhost"), int(env.get("VIZION_MQTT_PORT", "8883")))
            c.loop_start()
            self.client, self.enabled, self.detail = c, True, "connecting"
        except Exception as e:  # no paho, bad CA path...: Vizion keeps running without MQTT
            self.detail = f"off ({type(e).__name__}: {e})"
            print(f"MQTT unavailable: {self.detail}", flush=True)

    # paho callbacks (VERSION2 signatures; extra args ignored so tests can call them simply)
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        ok = not reason_code.is_failure if hasattr(reason_code, "is_failure") else reason_code == 0
        self.connected = ok
        self.detail = "connected" if ok else f"refused: {reason_code}"
        print(f"MQTT {self.detail}", flush=True)
        if ok:
            client.publish("vizion/status", "online", qos=1, retain=True)
            for topic in self.subscriptions:
                client.subscribe(topic, qos=1)

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False
        self.detail = "disconnected, retrying"

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except (ValueError, UnicodeDecodeError):
            payload = msg.payload.decode(errors="replace")
        with self._lock:
            for topic in self.subscriptions:
                if topic == msg.topic or (topic.endswith("#") and msg.topic.startswith(topic[:-1])):
                    self.subscriptions[topic] = {"payload": payload, "received": time.time()}

    def subscribe(self, topic):
        self.subscriptions.setdefault(topic, None)
        if self.client is not None and self.connected:
            self.client.subscribe(topic, qos=1)

    def latest(self, topic):
        with self._lock:
            return self.subscriptions.get(topic)

    def publish(self, topic, payload, every_s=None, retain=False):
        """Publishes when the payload changed, or when every_s has passed since the last publish."""
        if not self.enabled or self.client is None:
            return False
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        now = time.monotonic()
        last = self._last.get(topic)
        if last and last[0] == body and (every_s is None or now - last[1] < every_s):
            return False
        stamped = json.dumps({**payload, "ts": round(time.time(), 3)}, separators=(",", ":"))
        self.client.publish(topic, stamped, qos=1, retain=retain)
        self._last[topic] = (body, now)
        return True

    def state(self):
        return {"enabled": self.enabled, "connected": self.connected, "detail": self.detail}

    def close(self):
        if self.client is not None:
            try:
                self.client.publish("vizion/status", "offline", qos=1, retain=True)
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
