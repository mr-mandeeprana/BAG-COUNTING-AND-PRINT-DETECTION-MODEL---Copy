# FillPac AI

FillPac AI is an industrial computer vision system for cement bag counting and print presence inspection in a BEUMER FillPac packing plant.

## Features

- Single `YOLO26n` model for `Bag` and `Print` classes
- Center-based bag counting
- Print presence verification without OCR
- Multi-camera support for MP4 and RTSP sources
- FPS-oriented inference settings for CUDA half precision, resized inference, and low-latency capture buffers
- Live visualization, dashboard backend, and Elasticsearch event storage

## Project Structure

```text
FillPac_AI/
├── main.py
├── config.yaml
├── requirements.txt
├── README.md
├── models/
├── data/
├── src/
├── dashboard/
├── logs/
├── tests/
└── docs/
```

## Runtime Flow

```text
Camera -> YOLO26n Detection -> ByteTrack -> Counter + Print Detector -> Visualization
```

ByteTrack is used for detection stability only. Counting is based on bounding-box centers crossing the ROI and does not depend on track IDs.

## Cameras

- Camera 1: FillPac Opening 1, counting + print detection
- Camera 2: FillPac Opening 2, counting + print detection
- Camera 3: Truck Loading Conveyor 1, counting only
- Camera 4: Truck Loading Conveyor 2, counting only

## Quick Start

```bash
python -m pip install -r requirements.txt
python main.py
```

Expected model and dataset files:

- `models/fillpac_yolo26n_best.pt`
- `models/data.yaml`

## Runtime FPS Tuning

The main controls are in `config.yaml`:

- `model.image_size`: lower values improve FPS; raise toward `640` if accuracy drops.
- `model.half`: uses FP16 on CUDA for faster inference.
- `model.max_detections`: caps per-frame YOLO output work.
- `buffer_size`: keeps live camera/RTSP capture from lagging behind.

Dashboard backend:

```bash
uvicorn dashboard.backend.app:app --host 0.0.0.0 --port 8000
```

Training:

```bash
python train.py --epochs 50 --batch 8
```

## Elasticsearch Events

- `fillpac-count`
- `fillpac-print`
- `fillpac-camera`

## Tests

```bash
python -m pytest -q
```
