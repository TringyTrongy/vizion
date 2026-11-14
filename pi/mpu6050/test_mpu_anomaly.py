"""Checks the anomaly model's logic on SYNTHETIC signals (no sensor needed). These are unit tests
only; the real evidence is the Pi runs in data/."""
import numpy as np

import mpu_anomaly as ma


def signal(seconds, vib=0.01, rng=None, burst=0.0):
    rng = rng or np.random.default_rng(0)
    n = int(seconds * 100)
    sig = rng.normal(0, vib, (n, 6)) + np.array([0, 0, 1, 0, 0, 0])
    if burst:
        sig[:, 0] += burst * np.sin(np.arange(n) * 2 * np.pi * 7 / 100)
    return sig


def test_normal_is_quiet_and_fault_alerts():
    rng = np.random.default_rng(1)
    m = ma.Model.fit(np.vstack([ma.features(signal(60, rng=rng)) for _ in range(3)]))
    quiet = [m.alerts(ma.features(signal(60, rng=rng))) for _ in range(5)]
    assert sum(quiet) == 0, quiet
    assert m.alerts(ma.features(signal(30, rng=rng, burst=0.2))) >= 1


def test_one_bad_window_does_not_alert():
    rng = np.random.default_rng(2)
    m = ma.Model.fit(ma.features(signal(60, rng=rng)))
    sig = signal(20, rng=rng)
    sig[1020:1030, 0] += 1.0  # a 0.1 s knock touches 2 windows, fewer than the 3 needed
    assert m.alerts(ma.features(sig)) == 0


if __name__ == "__main__":
    test_normal_is_quiet_and_fault_alerts()
    print("ok  test_normal_is_quiet_and_fault_alerts")
    test_one_bad_window_does_not_alert()
    print("ok  test_one_bad_window_does_not_alert")
