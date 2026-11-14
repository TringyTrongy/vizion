# Vizion · architecture and software stack

## Data flow

```mermaid
flowchart LR
    CAM[USB webcam<br/>640x480 @ 15 fps] --> GRAB[FrameGrabber thread<br/>camera_preview.py]
    GRAB --> BAL[Colour balance<br/>detector.py]
    BAL --> DET[YOLO26n NCNN 480<br/>separate process, 3 cores]
    DET --> TRK[Tracker + debounce<br/>tracker.py]
    TRK --> DEC[Decision rules<br/>station.py]
    DEC --> LED[LEDs D1/D2<br/>GPIO17/27 · leds.py]
    DEC --> WEB[Dashboard + /station<br/>dashboard.py · web/]
    DEC --> MQ[(Mosquitto<br/>TLS 8883 + password)]
    MOTOR[Vizion Motor<br/>servo + camera] --> MQ
    MPU[MPU6050<br/>mpu6050/] --> ANOM[Anomaly model]
    MQ --> PLCB[PLC bridge<br/>plc/plc_bridge.py] --> PLC[PLC / OpenPLC<br/>Modbus TCP]
    MQ --> WEB
    LED --> LAT[latency.csv<br/>frame→LED]
    DEC --> ST[station.csv<br/>pass/fail score]
```

## Software stack (bottom to top)

| Layer | What | Version |
|---|---|---|
| Hardware | Raspberry Pi 5 4 GB (4× Cortex-A76 @ 2.4 GHz), Arkmicro USB2.0 webcam, LEDs, SG90 servo, MPU6050 | |
| OS | Raspberry Pi OS based on Debian 13 (64-bit) | |
| Runtime | Python 3.13 (container: 3.11), Docker (optional, `docker/`), systemd (`pi/system/`) | |
| Vision | OpenCV (capture, colour balance), Ultralytics 8.4.173 (model wrapper) | |
| Inference | **NCNN** on the CPU (ARM NEON), FP32, 480×480 input | about 41 ms/frame on 4 cores |
| Logic | tracker (debounce), station (pass/fail), latency log | this repo |
| I/O | gpiozero + lgpio (LEDs, servo), smbus2 (MPU6050 over I²C) | |
| Messaging | paho-mqtt 2.1 → Mosquitto 2.0 (TLS 1.2, password, ACL); pymodbus 3.8 → PLC | |
| UI | Python `http.server` + plain HTML/JS, Chromium kiosk | |

The Pi 5 has no NPU or GPU that NCNN can use here, so "accelerator" = the CPU's NEON SIMD units, with the detector in its own process so it runs in parallel with capture and the UI.
