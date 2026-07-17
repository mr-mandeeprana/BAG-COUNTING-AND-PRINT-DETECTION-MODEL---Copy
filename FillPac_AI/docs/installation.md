# Installation

## Prerequisites

- Python 3.10+
- A working Torch installation
- YOLO model file at `models/yolo26n.pt`
- Dataset config file at `models/data.yaml`

## Setup

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run FillPac AI

```bash
python main.py
```

## Train YOLO26n

```bash
python train.py --epochs 50 --batch 8
```

## Dataset Layout

```text
data/images/train
data/images/val
data/images/test
data/labels/train
data/labels/val
data/labels/test
```

## Run Dashboard Backend

```bash
uvicorn dashboard.backend.app:app --host 0.0.0.0 --port 8000
```

## Run Tests

```bash
python -m pytest -q
```
