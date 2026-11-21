from train import should_replace


def test_first_model_is_always_saved():
    assert should_replace(None, {"top_3_accuracy": 0.5})


def test_new_model_replaces_one_that_is_not_better():
    assert should_replace({"top_3_accuracy": 0.715}, {"top_3_accuracy": 0.71})


def test_clearly_worse_model_is_rejected():
    assert not should_replace({"top_3_accuracy": 0.715}, {"top_3_accuracy": 0.69})


def test_force_saves_even_a_worse_model():
    assert should_replace({"top_3_accuracy": 0.715}, {"top_3_accuracy": 0.2}, force=True)
