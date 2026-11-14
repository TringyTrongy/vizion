#!/usr/bin/env python3
"""Records labelled MPU6050 runs on the motor: accelerometer + gyro at 100 Hz to CSV.

Wiring (Pi 5 header): VCC -> pin 1 (3V3), GND -> pin 6, SDA -> pin 3 (GPIO2), SCL -> pin 5 (GPIO3).
Enable I2C first: sudo raspi-config -> Interface Options -> I2C, then `i2cdetect -y 1` shows 68.
Mount the board on the servo bracket so it feels the motor's vibration.

    python mpu_logger.py --label normal --run 1 --seconds 60     # data/normal_1.csv
    python mpu_logger.py --label fault  --run 1 --seconds 60     # e.g. tape a coin to the arm,
                                                                 # loosen a screw or hold the arm
Make 3 normal and 3 fault runs (the task), plus 5 extra normal runs for the false-alarm count.
"""
import argparse
import csv
import time
from pathlib import Path

ADDR = 0x68
PWR_MGMT_1, SMPLRT_DIV, CONFIG, GYRO_CONFIG, ACCEL_CONFIG, ACCEL_XOUT_H = 0x6B, 0x19, 0x1A, 0x1B, 0x1C, 0x3B
ACCEL_LSB_PER_G, GYRO_LSB_PER_DPS = 16384.0, 131.0  # +-2 g, +-250 deg/s
FIELDS = ["t_s", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps", "label", "run"]


def s16(hi, lo):
    v = (hi << 8) | lo
    return v - 65536 if v & 0x8000 else v


class Mpu6050:
    def __init__(self, bus=1, addr=ADDR):
        from smbus2 import SMBus

        self.bus, self.addr = SMBus(bus), addr
        self.bus.write_byte_data(addr, PWR_MGMT_1, 0)      # wake up
        self.bus.write_byte_data(addr, SMPLRT_DIV, 9)      # 1 kHz / (1 + 9) = 100 Hz
        self.bus.write_byte_data(addr, CONFIG, 3)          # 44 Hz low-pass
        self.bus.write_byte_data(addr, GYRO_CONFIG, 0)
        self.bus.write_byte_data(addr, ACCEL_CONFIG, 0)

    def read(self):
        d = self.bus.read_i2c_block_data(self.addr, ACCEL_XOUT_H, 14)
        ax, ay, az = (s16(d[i], d[i + 1]) / ACCEL_LSB_PER_G for i in (0, 2, 4))
        gx, gy, gz = (s16(d[i], d[i + 1]) / GYRO_LSB_PER_DPS for i in (8, 10, 12))
        return ax, ay, az, gx, gy, gz


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True, choices=["normal", "fault"])
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--hz", type=float, default=100)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.label}_{args.run}.csv"
    mpu = Mpu6050()
    period, n = 1 / args.hz, 0
    t0 = nxt = time.monotonic()
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        while (now := time.monotonic()) - t0 < args.seconds:
            w.writerow([round(now - t0, 4), *(round(v, 5) for v in mpu.read()), args.label, args.run])
            n += 1
            nxt += period
            time.sleep(max(0.0, nxt - time.monotonic()))
    print(f"Wrote {path}: {n} samples, {n / args.seconds:.1f} Hz")


if __name__ == "__main__":
    main()
