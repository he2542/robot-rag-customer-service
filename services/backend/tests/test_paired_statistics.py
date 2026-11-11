import pytest

from evaluation.paired_statistics import paired_binary, percentile, wilson


def rows(pairs, cluster=None):
    return [{"source": "source", "cluster": str(i) if cluster is None else cluster,
             "before": a, "after": b} for i, (a, b) in enumerate(pairs)]


def test_point_difference_is_paired_percentage_points():
    result = paired_binary(rows([(False, True)] * 4 + [(True, False)] + [(True, True)] * 5), 200)
    assert result["before_correct"] == 6
    assert result["after_correct"] == 9
    assert result["delta_pp"] == 30
    assert result["wins"] == 4 and result["losses"] == 1
    assert result["mcnemar_exact_iid_sensitivity_p"] == .375


def test_unchanged_answers_have_zero_paired_interval():
    result = paired_binary(rows([(True, True), (False, False)] * 10), 200)
    assert result["delta_95_cluster_bootstrap_pp"] == [0, 0]
    assert result["mcnemar_exact_iid_sensitivity_p"] == 1


def test_source_weights_preserved_under_cluster_resampling():
    data = rows([(False, True)] * 8, cluster="shared")
    data += [{"source": "other", "cluster": "one", "before": True, "after": False}] * 2
    result = paired_binary(data, 200)
    assert result["clusters"] == 2 and result["strata"] == 2
    assert result["delta_pp"] == 60
    assert result["delta_95_cluster_bootstrap_pp"] == pytest.approx([60, 60])


def test_bootstrap_reproducibility_and_interval_order():
    data = rows([(False, True), (True, False), (True, True), (False, False)] * 4)
    first = paired_binary(data, 200, 7)
    assert first == paired_binary(data, 200, 7)
    lo, hi = first["delta_95_cluster_bootstrap_pp"]
    assert -100 <= lo <= first["delta_pp"] <= hi <= 100


def test_wilson_limits_and_interpolation():
    assert wilson(0, 300)[0] == pytest.approx(0)
    assert 0.012 < wilson(0, 300)[1] < 0.013
    assert wilson(300, 300)[1] == pytest.approx(1)
    assert percentile([0, 10], .25) == 2.5


def test_invalid_sample_is_rejected():
    with pytest.raises(ValueError):
        paired_binary([])
    with pytest.raises(TypeError):
        paired_binary([{"source": "a", "cluster": "a", "before": 1, "after": True}], 2)
