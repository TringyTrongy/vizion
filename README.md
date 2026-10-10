# Vizion

Resistor and capacitor detection on a Raspberry Pi 5 with a USB webcam. A YOLO26n model runs on the Pi's CPU (NCNN). A full-screen dashboard shows what it sees, and two LEDs light up for resistors and capacitors.

![The Vizion dashboard](docs/dashboard.jpg)

| Path | Contents |
|---|---|
| [`pi/`](pi) | Everything that runs on the Pi: dashboard, camera preview, detector, tracker, LED driver, launchers, tests. Setup, controls and LED wiring are in [pi/README.md](pi/README.md) |
| [`pi/motor_monitor/`](pi/motor_monitor) | **Vizion Motor**: watches the SG90 servo arm with the webcam, compares every frame with pictures of normal movement it learned, and stops the motor when they don't match (an anomaly). Guide in [its README](pi/motor_monitor/README.md) |
| [`model/`](model) | The detector: NCNN model, PyTorch weights, training record and the [model card](model/README.md) (results, colour balance, training data, limitations) |
| [`data/`](data) | The training dataset in YOLO format (2197 images) and the labelled webcam frames. Sources and licences are in [data/README.md](data/README.md) |
| [`scripts/`](scripts) | The training pipeline: download, prepare, train, evaluate, export |
| [`PRODUCT.md`](PRODUCT.md), [`DESIGN.md`](DESIGN.md), `.impeccable/` | The dashboard's product brief and design system (the "Schematic Sheet" look) |
| `capture_*.jpg` | The first webcam frames (610×480): a single resistor (`…150640_858`) and a single capacitor (`…150729_589`) |

## On the Pi

```sh
cd ~/vizion
./run_dashboard.sh     # the camera: resistors and capacitors
./run_motor.sh         # Vizion Motor: the servo arm
```

[pi/README.md](pi/README.md) covers installing from scratch.

## Retraining

On a computer with an NVIDIA GPU (v3 took 32 minutes on an RTX 4060 Laptop GPU), with PyTorch and `ultralytics` 8.4.173 installed:

```sh
python scripts/train.py --model yolo26n.pt --epochs 100 --patience 25 --name yolo26n_v4
python scripts/webcam_check.py runs/yolo26n_v4/weights/best.pt --imgsz 480
python scripts/evaluate.py --run yolo26n_v4
python scripts/export.py --run yolo26n_v4      # writes pi/models/vizion_ncnn_model; copy it to ~/vizion/models/
```

On Windows, run these as `.py` files, not through stdin. The dataloader workers re-import the script.

## Licence

The model is fine-tuned from Ultralytics YOLO26 (AGPL-3.0) and inherits that licence. One training source does not state a licence, so keep this repository private unless its author allows redistribution; [data/README.md](data/README.md) has the details. The camera dashboard's font is osifont (LGPL-3 with font exception); Vizion Motor uses Barlow (SIL Open Font License, `pi/motor_monitor/web/fonts/OFL.txt`).
