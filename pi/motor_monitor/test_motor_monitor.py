"""Tests for Vizion Motor, on the simulated rig and a made-up clock: no camera or GPIO needed.

    python motor_monitor/test_motor_monitor.py
"""
import argparse
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import motor_dashboard as md  # noqa: E402
import motor_watch as mw  # noqa: E402
from motor_rig import SimRig  # noqa: E402
from motor_watch import ANOMALY, LEARNING, NO_CAMERA, NOT_LEARNED, STOPPED, WATCHING, Monitor, grey_small  # noqa: E402

FPS = 8.5


class Bench:
    """A Monitor and a simulated rig on a made-up clock."""

    def __init__(self, master=None):
        self.rig = SimRig(realtime=False)
        self.rows = []
        self.kept = 0
        self.m = Monitor(master, record=self.rows.append, keep=self._keep)
        self.t = 1000.0

    def _keep(self, frame):
        self.kept += 1
        return b"jpeg"

    def run(self, seconds, frames=True):
        dt = 1 / FPS
        for _ in range(int(round(seconds * FPS))):
            for k in range(3):  # the servo is updated more often than the camera sees it
                ts = self.t + k * dt / 3
                self.rig.servo(self.m.command(ts)[0])
                self.rig._move(ts)
            self.t += dt
            self.rig.servo(self.m.command(self.t)[0])
            self.m.check_camera(self.t)
            if frames:
                f = self.rig.frame_at(self.t)
                self.m.on_frame(grey_small(f), self.t, f)

    def started(self):
        """A bench with the shared master, watching (it needs one camera frame before Start)."""
        self.run(0.5)
        self.m.start(self.t)
        return self


MASTER = None


def setUpModule():
    global MASTER
    b = Bench()
    b.m.learn(b.t)
    b.run(mw.SETTLE_S + mw.LEARN_S + 0.5)
    assert b.m.state == WATCHING, b.m.reason
    MASTER = b.m.master


class Learning(unittest.TestCase):
    def test_learns_the_arm_region_and_a_limit(self):
        self.assertGreaterEqual(MASTER.limit, mw.LIMIT_FLOOR)
        self.assertLess(MASTER.normal_p99, mw.UNSTEADY)
        x0, y0, x1, y1 = MASTER.box
        # the drawn arm turns about (305, 260) in the full frame, (152, 130) at half size
        self.assertTrue(x0 < 152 < x1 and y0 < 130 < y1, MASTER.box)
        self.assertGreater(len(MASTER.us), mw.MIN_SWEEP_FRAMES)
        self.assertGreaterEqual(len(MASTER.still), mw.MIN_STILL_FRAMES)

    def test_learning_holds_still_then_sweeps_and_carries_on_watching(self):
        b = Bench()
        b.m.learn(b.t)
        self.assertEqual(b.m.command(b.t + 0.5), (mw.MIDDLE_US, 0))
        self.assertEqual(b.m.leds(b.t + 0.2), {"yellow": True, "red": False})  # blinking
        b.run(mw.SETTLE_S + 1)
        self.assertNotEqual(b.m.command(b.t)[0], mw.MIDDLE_US)
        b.run(mw.LEARN_S)
        self.assertEqual(b.m.state, WATCHING)
        self.assertGreater(b.kept, 200)  # a picture kept for every master image
        self.assertTrue(any(e["kind"] == "learned" for e in b.m.events))

    def test_fails_when_the_arm_does_not_move(self):
        b = Bench()
        b.rig.disturb("freeze")  # like a servo with no power
        b.m.learn(b.t)
        b.run(mw.SETTLE_S + mw.LEARN_S + 0.5)
        self.assertEqual(b.m.state, NOT_LEARNED)
        self.assertIn("didn't see the arm move", b.m.reason)
        self.assertIsNone(b.m.master)

    def test_fails_without_enough_pictures(self):
        b = Bench()
        b.m.learn(b.t)
        b.run(1.0)
        b.t += mw.SETTLE_S + mw.LEARN_S  # the camera was nearly silent all along
        f = b.rig.frame_at(b.t)
        b.m.on_frame(grey_small(f), b.t, f)
        self.assertEqual(b.m.state, NOT_LEARNED)
        self.assertIn("too dark", b.m.reason)

    def test_a_failed_relearn_keeps_the_earlier_normal(self):
        b = Bench(MASTER).started()
        b.rig.disturb("freeze")
        b.m.learn(b.t)
        b.run(mw.SETTLE_S + mw.LEARN_S + 0.5)
        self.assertIs(b.m.master, MASTER)
        self.assertEqual(b.m.state, STOPPED)
        self.assertIn("earlier normal is still in use", b.m.reason)


class Watching(unittest.TestCase):
    def test_normal_sweeping_never_trips(self):
        b = Bench(MASTER).started()
        b.run(20)
        self.assertEqual(b.m.state, WATCHING)
        self.assertEqual(b.m.counts["anomalies"], 0)
        self.assertGreaterEqual(b.m.counts["sweeps"], 6)
        self.assertEqual(b.m.leds(b.t), {"yellow": True, "red": False})
        snap = b.m.snapshot(b.t)
        self.assertLess(snap["now"]["mismatch"], MASTER.limit)
        self.assertIsNotNone(snap["now"]["seen_deg"])

    def test_a_hand_on_the_arm_trips_and_stops_the_motor(self):
        b = Bench(MASTER).started()
        b.run(4)
        b.rig.disturb("hold")
        t_hold = b.t
        b.run(1.0)
        self.assertEqual(b.m.state, ANOMALY)
        trip = b.m.trip
        self.assertGreater(trip["score"], MASTER.limit)
        self.assertEqual(trip["while"], "sweeping")
        self.assertEqual(b.m.command(b.t), (0, 0))  # no pulses: the arm is limp
        reds = {b.m.leds(b.t + k * 0.1)["red"] for k in range(6)}
        self.assertEqual(reds, {True, False})  # flashing
        self.assertIn("Restart", b.m.reason)
        self.assertEqual(b.m.events[-1]["kind"], "anomaly")
        self.assertEqual(b.m.trip["id"], b.m.events[-1]["id"])
        # within CONFIRM frames of the hand arriving (plus one for the frame in flight)
        trip_t = [s[1] for s in b.m.trace if s[5] == "A"][0]
        self.assertLessEqual(trip_t - t_hold, (mw.CONFIRM + 1) / FPS + 1e-6)
        self.assertEqual(b.rows[-1]["state"], ANOMALY)

    def test_an_arm_that_stops_moving_says_so(self):
        b = Bench(MASTER).started()
        b.run(4)
        b.rig.disturb("freeze")
        b.run(2)
        self.assertEqual(b.m.state, ANOMALY)
        self.assertTrue("stopped moving" in b.m.trip["text"] or "was at about" in b.m.trip["text"],
                        b.m.trip["text"])

    def test_restart_carries_on_and_does_not_trip_again(self):
        b = Bench(MASTER).started()
        b.run(3)
        b.rig.disturb("hold")
        b.run(1)
        self.assertEqual(b.m.state, ANOMALY)
        b.rig.disturb("release")
        b.m.restart(b.t)
        b.run(10)
        self.assertEqual(b.m.state, WATCHING)
        self.assertEqual(b.m.counts["anomalies"], 1)

    def test_covering_the_camera_trips(self):
        b = Bench(MASTER).started()
        b.run(3)
        b.rig.disturb("cover")
        b.run(1)
        self.assertEqual(b.m.state, ANOMALY)

    def test_a_push_while_stopped_is_an_anomaly(self):
        b = Bench(MASTER).started()
        b.run(3)
        b.m.stop(b.t)
        self.assertEqual(b.m.command(b.t + 0.1), (mw.MIDDLE_US, 0))  # parks in the middle...
        self.assertEqual(b.m.command(b.t + mw.PARK_S + 0.1), (0, 0))  # ...then no pulses
        b.run(4)
        self.assertEqual(b.m.state, STOPPED)
        b.rig.disturb("nudge")
        b.run(1)
        self.assertEqual(b.m.state, ANOMALY)
        self.assertIn("moved while the motor was stopped", b.m.trip["text"])

    def test_no_push_check_straight_after_loading_a_saved_normal(self):
        b = Bench(MASTER)
        b.rig.disturb("nudge")  # the arm was left somewhere else
        b.run(4)
        self.assertEqual(b.m.state, STOPPED)
        self.assertEqual(b.m.counts["anomalies"], 0)


class Controls(unittest.TestCase):
    def test_start_needs_a_normal_and_a_camera(self):
        b = Bench()
        b.run(0.5)
        with self.assertRaises(ValueError):
            b.m.start(b.t)
        b = Bench(MASTER)
        with self.assertRaises(ValueError):  # no camera frame yet
            b.m.start(b.t)

    def test_a_silent_camera_stops_the_motor(self):
        b = Bench(MASTER).started()
        b.run(2)
        b.run(3, frames=False)
        self.assertEqual(b.m.state, NO_CAMERA)
        self.assertEqual(b.m.command(b.t), (0, 0))
        with self.assertRaises(ValueError):
            b.m.restart(b.t)  # still no pictures
        b.run(0.5)
        b.m.restart(b.t)
        self.assertEqual(b.m.state, WATCHING)

    def test_stop_while_learning_cancels(self):
        b = Bench(MASTER).started()
        b.m.learn(b.t)
        b.run(3)
        b.m.stop(b.t)
        self.assertEqual(b.m.state, STOPPED)
        self.assertIs(b.m.master, MASTER)

    def test_snapshot_trace_is_incremental(self):
        b = Bench(MASTER).started()
        b.run(2)
        snap = b.m.snapshot(b.t)
        seq = snap["seq"]
        b.run(1)
        later = b.m.snapshot(b.t, after=seq)
        self.assertTrue(all(p[0] > seq for p in later["trace"]))
        self.assertEqual(len(later["trace"]), round(FPS))


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="vizion-motor-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_master_round_trip(self):
        path = self.dir / "master.npz"
        md.save_master(MASTER, path)
        back = md.load_master(path)
        self.assertEqual(back.box, MASTER.box)
        self.assertAlmostEqual(back.limit, MASTER.limit)
        self.assertEqual(len(back.keeps), len(MASTER.keeps))
        b = Bench(MASTER).started()
        b.run(1)
        f = b.rig.frame_at(b.t)
        v1, v2 = MASTER.vector(grey_small(f)), back.vector(grey_small(f))
        self.assertEqual(MASTER.inspect(v1, 1500, 1)[:2], back.inspect(v2, 1500, 1)[:2])

    def test_recorder_writes_and_exports(self):
        rec = md.Recorder(self.dir / "log")
        for ts, state in (("2026-10-09 23:59:59", "WATCHING"), ("2026-10-10 00:00:01", "ANOMALY")):
            rec.write({"timestamp": ts, "state": state, "command_us": 1500, "command_deg": 0.0, "seen_deg": "",
                       "mismatch": "0.5000", "limit": "0.1500", "event": ""})
        rec.flush()
        self.assertEqual(sorted(p.name for p in (self.dir / "log").iterdir()),
                         ["motor-watch-2026-10-09.csv", "motor-watch-2026-10-10.csv"])
        everything = rec.export().splitlines()
        self.assertEqual(everything[0], ",".join(md.COLUMNS))
        self.assertEqual(len(everything), 3)
        self.assertEqual(len(rec.export(since="2026-10-10 00:00:00").splitlines()), 2)
        self.assertEqual(len(rec.export(day="2026-10-09").splitlines()), 2)

    def test_plate_box_stays_inside_the_frame(self):
        (x, y, w, h), box = md.plate_box(MASTER)
        self.assertTrue(0 <= x and 0 <= y and x + w <= 610 and y + h <= 480)
        self.assertTrue(all(0 <= v <= 1 for v in box))
        self.assertEqual(md.plate_box(None), ((0, 0, 610, 480), None))


class Server(unittest.TestCase):
    """The HTTP API against the simulated rig in real time (a couple of seconds)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="vizion-motor-"))
        args = argparse.Namespace(rig="sim", leds="on", fresh=True, no_log=False, data=str(self.dir), verbose=False)
        self.app = md.App(args)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), md.Handler)
        self.server.daemon_threads = True
        self.server.app, self.server.verbose = self.app, False
        self.app.start()
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.headers, r.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_page_state_controls_and_export(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Vizion Motor", body)
        for asset in ("/static/motor.css", "/static/motor.js", "/static/fonts/barlow-condensed-700.woff2"):
            self.assertEqual(self.get(asset)[0], 200, asset)
        threading.Event().wait(0.8)  # a few camera frames
        state = json.loads(self.get("/api/state")[2])
        self.assertEqual(state["state"], NOT_LEARNED)
        self.assertTrue(state["rig"]["simulated"])
        self.assertGreater(state["frames"], 0)
        self.assertEqual(self.post("/api/control", {"action": "start"})[0], 409)  # nothing learned yet
        self.assertEqual(self.post("/api/control", {"action": "learn"}), (200, {"ok": True, "state": LEARNING}))
        self.assertEqual(self.post("/api/control", {"action": "learn"})[0], 409)
        self.assertEqual(self.post("/api/control", {"action": "nonsense"})[0], 409)
        threading.Event().wait(0.6)  # a few frames recorded while learning
        self.assertEqual(self.post("/api/sim", {"action": "hold"}), (200, {"ok": True}))
        status, headers, body = self.get("/api/plate/live.jpg")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/jpeg"))
        self.assertTrue(body.startswith(b"\xff\xd8"))
        self.assertEqual(self.post("/api/control", {"action": "stop"}), (200, {"ok": True, "state": NOT_LEARNED}))
        threading.Event().wait(1.2)  # the log is written once a second
        status, headers, body = self.get("/api/export?range=session")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        lines = body.decode().splitlines()
        self.assertEqual(lines[0], ",".join(md.COLUMNS))
        self.assertGreater(len(lines), 1)
        for sneaky in ("/static/../motor_dashboard.py", "/static/..%2Fmotor_dashboard.py"):
            with self.assertRaises(urllib.error.HTTPError, msg=sneaky) as caught:
                self.get(sneaky)
            caught.exception.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
