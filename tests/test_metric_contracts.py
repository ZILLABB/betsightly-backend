from growth.metric_contracts import conversion


def test_conversion_labels_small_samples_and_never_exceeds_one():
    assert conversion(2, 4)["rate"] is None
    assert conversion(2, 4)["sample_status"] == "insufficient"
    low = conversion(20, 25)
    assert low == {"numerator": 20, "denominator": 25,
                   "rate": 0.8, "sample_status": "low"}
    assert conversion(60, 50)["rate"] == 1.0


def test_conversion_uses_normal_label_at_adequate_sample():
    assert conversion(25, 50)["sample_status"] == "normal"
