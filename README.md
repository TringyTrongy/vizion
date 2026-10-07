# Vizion

Resistor and capacitor detection on a Raspberry Pi 5 with a USB webcam.

| Path | Contents |
|---|---|
| [`model/`](model) | The detector: NCNN model for the Pi, PyTorch weights, training record and the [model card](model/README.md) (results, training data, usage, limitations) |
| `capture_*.jpg` | Frames from the Pi webcam (610×480): a single resistor (`…150640_858`) and a single capacitor (`…150729_589`) |
