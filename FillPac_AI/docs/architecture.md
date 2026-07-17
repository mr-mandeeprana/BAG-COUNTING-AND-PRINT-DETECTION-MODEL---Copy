# Architecture

## Overview

FillPac AI processes MP4 videos or RTSP streams through a shared industrial vision pipeline:

```text
Camera
  -> YOLO26n Detection (Bag + Print)
  -> ByteTrack
  -> Center Counter
  -> Print Detector
  -> Visualizer
  -> Dashboard / Elasticsearch
```

## Core Rules

- One `YOLO26n` model handles both bag and print detection.
- Runtime FPS is tuned through `model.image_size`, CUDA `model.half`, `model.max_detections`, and per-camera `buffer_size`.
- ByteTrack improves detection stability only.
- Counting uses center crossing plus duplicate filtering.
- Track IDs do not control the count.
- Cameras 1 and 2 run print detection.
- Cameras 3 and 4 run bag counting only.

## Main Modules

- `src/application.py`: boots config, logging, and pipelines
- `src/pipeline.py`: camera runtime flow
- `src/camera.py`: MP4/RTSP capture and reconnect support
- `src/detector.py`: YOLO inference
- `src/tracker.py`: stable bag tracking
- `src/counter.py`: center-based counting
- `src/print_detector.py`: print-in-bag validation
- `src/visualizer.py`: rendering wrapper
- `src/elasticsearch.py`: event publishing
- `src/dashboard.py`: runtime event broadcast helper

## Dashboard Data

The dashboard backend exposes:

- camera health
- per-camera count
- print status
- fps
- system status
