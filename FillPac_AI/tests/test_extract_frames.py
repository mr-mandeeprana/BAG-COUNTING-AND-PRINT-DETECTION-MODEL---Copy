from extract_frames import choose_split


def test_choose_split_defaults_to_train_for_single_item():
    assert choose_split(0, 1) == "train"


def test_choose_split_spreads_items_across_splits():
    assert choose_split(0, 10) == "train"
    assert choose_split(7, 10) == "val"
    assert choose_split(9, 10) == "test"
