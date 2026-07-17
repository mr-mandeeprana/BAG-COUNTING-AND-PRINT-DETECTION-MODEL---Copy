from pathlib import Path


def test_training_entrypoint_exists():
    assert Path("train.py").exists()


def test_training_dataset_yaml_exists():
    assert Path("models/data.yaml").exists()
