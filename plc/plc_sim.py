#!/usr/bin/env python3
"""A software PLC for testing the PLC link without hardware: a Modbus TCP server that prints and
logs every tag change it receives (the "PLC tag changed" evidence).

    python plc_sim.py --port 5020

On the real system the same tags live in the OpenPLC runtime (see README.md); the bridge does
not care which one it talks to.
"""
import argparse
import csv
import time
from pathlib import Path

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext

try:
    from pymodbus.datastore import ModbusDeviceContext as DeviceContext  # pymodbus >= 3.10
except ImportError:
    from pymodbus.datastore import ModbusSlaveContext as DeviceContext
from pymodbus.server import StartTcpServer

from plc_bridge import COILS, REGS


class LoggingBlock(ModbusSequentialDataBlock):
    def __init__(self, kind, names, log):
        super().__init__(0, [0] * 16)
        self.kind, self.names, self.log = kind, names, log

    def setValues(self, address, values):
        old = self.getValues(address, len(values))
        super().setValues(address, values)
        for i, (a, b) in enumerate(zip(old, values)):
            if int(a) != int(b):
                # pymodbus passes 1-based addresses to the block
                idx = address - 1 + i
                name = self.names[idx] if 0 <= idx < len(self.names) else f"{self.kind}{idx}"
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{stamp}  PLC TAG {name} {int(a)} -> {int(b)}", flush=True)
                self.log.writerow([stamp, name, int(a), int(b)])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--log", default=str(Path(__file__).resolve().parent / "logs" / "plc_tags.csv"))
    args = ap.parse_args()
    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    f = open(args.log, "a", newline="")
    log = csv.writer(f)
    log.writerow(["wall_time", "tag", "from", "to"])
    f.flush()

    class Flushing:
        def writerow(self, row):
            log.writerow(row)
            f.flush()

    device = DeviceContext(co=LoggingBlock("coil", COILS, Flushing()), hr=LoggingBlock("reg", REGS, Flushing()),
                           di=ModbusSequentialDataBlock(0, [0] * 16), ir=ModbusSequentialDataBlock(0, [0] * 16))
    try:
        context = ModbusServerContext(devices=device, single=True)
    except TypeError:
        context = ModbusServerContext(slaves=device, single=True)
    print(f"Simulated PLC on Modbus TCP port {args.port}", flush=True)
    StartTcpServer(context=context, address=("0.0.0.0", args.port))


if __name__ == "__main__":
    main()
