import pytest

from text_utils import normalize_text
from value_fuzzy_matcher import suggest


def test_typo_suggests_country():
    result = suggest('colmbia', [(1, 'colombia'), (2, 'peru')])
    assert result.key == 1
    assert result.label == 'colombia'
    assert result.score == pytest.approx(93.3, abs=0.1)
    assert result.ambiguous is False


def test_typo_suggests_selection_option():
    result = suggest('persna', [('person', 'person'), ('company', 'company')])
    assert result.key == 'person'
    assert result.score == pytest.approx(83.3, abs=0.1)
    assert result.ambiguous is False


def test_substring_candidate_is_not_suggested():
    assert suggest('guinea', [(1, 'papua new guinea')]) is None


def test_identical_candidates_are_ambiguous():
    result = suggest('santandr', [(1, 'santander'), (2, 'santander')])
    assert result is not None
    assert result.ambiguous is True


def test_below_threshold_returns_none():
    assert suggest('xyz', [(1, 'colombia')]) is None
    assert suggest('colmbia', [(1, 'colombia')], threshold=99) is None


def test_empty_inputs_return_none():
    assert suggest('', [(1, 'colombia')]) is None
    assert suggest('colmbia', []) is None


def test_normalize_text():
    assert normalize_text('  Bogotá  ') == 'bogota'
    assert normalize_text('ÁÉÍÓÚ ñ') == 'aeiou n'
    assert normalize_text(None) == ''
    assert normalize_text(12) == '12'


def test_same_key_twice_is_not_ambiguous():
    # one record with the same name in two languages
    result = suggest('santandr', [(1, 'santander'), (1, 'santander')])
    assert result is not None
    assert result.key == 1
    assert result.ambiguous is False


def test_different_keys_same_label_is_ambiguous():
    result = suggest('santandr', [(1, 'santander'), (2, 'santander')])
    assert result is not None
    assert result.ambiguous is True


def test_same_key_duplicates_do_not_hide_real_ambiguity():
    result = suggest('santandr', [(1, 'santander'), (1, 'santander'), (2, 'santander')])
    assert result.ambiguous is True
