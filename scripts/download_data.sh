#!/bin/sh
# Downloads the raw datasets into data/raw/<name>/ds.zip (no accounts needed).
#   ElectroCom61  - CC BY 4.0, YOLO format, 61 classes  (Mendeley Data 10.17632/6scy6h8sjz.2)
#   kaggle_rdci   - akeshm/resistor-diode-capacitor-ic, YOLO labels, license not stated
#   kaggle_resseg - alptugaydin/resistor-images-dataset-for-segmentation, CC BY 4.0, COCO masks
set -e
cd "$(dirname "$0")/.."
get() {
    mkdir -p "data/raw/$1"
    [ -s "data/raw/$1/ds.zip" ] && { echo "$1: already downloaded"; return; }
    curl -fsSL --retry 3 -o "data/raw/$1/ds.zip" "$2"
}
get electrocom61 "https://data.mendeley.com/public-api/zip/6scy6h8sjz/download/2"
get kaggle_rdci "https://www.kaggle.com/api/v1/datasets/download/akeshm/resistor-diode-capacitor-ic"
get kaggle_resseg "https://www.kaggle.com/api/v1/datasets/download/alptugaydin/resistor-images-dataset-for-segmentation"
