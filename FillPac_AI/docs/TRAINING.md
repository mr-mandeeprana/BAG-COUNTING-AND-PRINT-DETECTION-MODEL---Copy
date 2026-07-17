# Training

## Default Model

This project is aligned to train from `models/yolo26n.pt`.

## Dataset Files

- dataset yaml: `models/data.yaml`
- train images: `data/images/train`
- val images: `data/images/val`
- test images: `data/images/test`
- train labels: `data/labels/train`
- val labels: `data/labels/val`
- test labels: `data/labels/test`

## Start Training

```bash
python train.py --epochs 50 --batch 8
```

## Force CPU

```bash
python train.py --device cpu --epochs 50 --batch 8
```

## Resume Training

```bash
python train.py --resume
```

The resume checkpoint is expected at:

```text
runs/train/fillpac_yolo26n/weights/last.pt
```

## Expected Output

- best weights: `runs/train/fillpac_yolo26n/weights/best.pt`
- last weights: `runs/train/fillpac_yolo26n/weights/last.pt`

After training, copy the checkpoint you want to deploy into:

```text
models/yolo26n.pt
```
