# Vizion training dataset

The exact dataset the [v3 detector](../model) was trained on, in YOLO format: 2197 images, 2 classes.

| Class | ID | Box covers |
|---|---|---|
| resistor | 0 | the body only, not the leads |
| capacitor | 1 | the body only, not the legs (all types: electrolytic, ceramic, film, MLCC) |

## Layout

```
dataset/
  data.yaml              # Ultralytics dataset file (paths relative to it)
  train/images, train/labels
  val/images,   val/labels
  test/images,  test/labels
  webcam/                # source of the real-camera frames, plus the held-out scene
    labels.json          # hand-checked pixel boxes for 15 webcam frames (4 scenes)
    raw/                 # the 15 original 610×480 frames
    test/                # held-out scene s3: 1 frame, YOLO labels, test.yaml
```

Each `labels/*.txt` has one line per part, `class x_center y_center width height`, normalised to 0–1. An empty file means the image has no resistor or capacitor (a negative example).

## Splits

| Split | Images | Resistor boxes | Capacitor boxes | Images with no parts |
|---|---|---|---|---|
| train | 1779 | 1427 | 2885 | 330 |
| val | 307 | 59 | 392 | 53 |
| test | 111 | 75 | 162 | 24 |

## Sources

The filename prefix says where each image came from.

| Prefix | Source | Licence | train / val / test | How it was processed |
|---|---|---|---|---|
| `ec61_` | [ElectroCom61](https://data.mendeley.com/datasets/6scy6h8sjz/2) | CC BY 4.0 | 700 / 248 / 49 | Its 6 capacitor classes merged into one. Capacitor boxes shrunk to the body automatically (GrabCut, then an opening that removes the thin legs); images where that failed were dropped. Images with resistors dropped, since their boxes include the leads. Look-alike parts (inductors, diodes, Zener diodes, fuses, NTC thermistors) kept as negatives. |
| `rdci_` | [Kaggle: resistor-diode-capacitor-ic](https://www.kaggle.com/datasets/akeshm/resistor-diode-capacitor-ic) | **Not stated** | 352 / 46 / 50 | Rotated to their EXIF orientation (the labels match that view), cut into overlapping 1600 px tiles, saved at most 1280 px |
| `resseg_` | [Kaggle: resistor-images-dataset-for-segmentation](https://www.kaggle.com/datasets/alptugaydin/resistor-images-dataset-for-segmentation) | CC BY 4.0 | 103 / 13 / 12 | Resistor outlines converted to boxes |
| `webcam_` | Vizion's own USB webcam | Own | 24 / 0 / 0 | The 14 labelled frames of scenes s1, s2 and s4 from `webcam/labels.json`. s1 and s2 have one frame each and are repeated 6 times; s4's 12 frames appear once. |
| `synth_` | Generated from the webcam frames | Own | 600 / 0 / 0 | The real parts cut out (GrabCut) and pasted at random angles and sizes onto the empty table |

Half of the public training images were also degraded to look like the webcam: softened, noisy, colour-shifted and JPEG-compressed. Validation and test images are unmodified.

Scene s3 (`webcam/test/`, one capacitor and one resistor) never appears in training. It is the real-camera check.

## Training with it

The settings used for v3 are in [`../model/training/args.yaml`](../model/training/args.yaml). In short:

```python
from ultralytics import YOLO

model = YOLO("yolo26n.pt")
model.train(data="dataset/data.yaml", imgsz=640, epochs=100, patience=25, batch=16,
            flipud=0.5, degrees=10, cache="ram")
model.val(data="dataset/data.yaml", split="test", imgsz=480)
model.val(data="dataset/webcam/test/test.yaml", imgsz=480)   # held-out webcam scene
```

To add new webcam frames, label them body-only in `webcam/labels.json` (pixel boxes `[class, x0, y0, x1, y1]`) and convert them to YOLO lines. More varied real-camera scenes are the best way to improve the model.

## Licence

- ElectroCom61: M. F. A. Sayeedi et al., *ElectroCom61: A Multiclass Dataset for Detection of Electronic Components*, Mendeley Data V2, doi:[10.17632/6scy6h8sjz.2](https://doi.org/10.17632/6scy6h8sjz.2), CC BY 4.0. The images here are modified (relabelled, boxes changed, some degraded).
- Resistor segmentation images: alptugaydin, Kaggle, CC BY 4.0. Modified (outlines converted to boxes, some degraded).
- The `rdci_` images come from a Kaggle dataset that does not state a licence. Keep this repository private, or remove those images, unless the author gives permission to redistribute them.
- Webcam and synthetic images: made for this project.
