"""Tests for the shared pieces: normalising text and the ISIN check digit."""

import pytest

from fundcrosscheck.common import isin_is_valid, normalise


@pytest.mark.parametrize("raw, expected", [
    ("We have classiﬁed this product as 5 out of 7", "We have classified this product as 5 out of 7"),  # F12 ligature
    ("Identiﬁer: GB0031429219", "Identifier: GB0031429219"),                                          # F12
    ("classifies this product as ‘4’ out of ‘7’", "classifies this product as '4' out of '7'"),       # F10 curly quotes
    ("Product Name: AVI Global Trust plc (the “Company”)", 'Product Name: AVI Global Trust plc (the "Company")'),  # F05
    ("One‐off costs", "One-off costs"),                                                               # F10 U+2010 hyphen
    ("Management fees and other\nadministrative or operating costs",
     "Management fees and other administrative or operating costs"),                                  # F04 split label
    ("  RIT’s  ISIN is\tGB0007366395 ", "RIT's ISIN is GB0007366395"),                                # F10 double spaces
])
def test_normalise(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.parametrize("isin", [
    "GB00BS88V647",  # F16
    "JE00B1GXH751",  # F04, Jersey
    "IE00BYVJRH94",  # F07, Ireland
    "GB0007816068",  # F09
    "GB0031429219",  # F12
])
def test_real_isins_pass(isin):
    assert isin_is_valid(isin)


@pytest.mark.parametrize("isin", [
    "GB00BS88V646",   # wrong check digit
    "JE00B1GXH752",   # wrong check digit
    "gb00bs88v647",   # lower case
    "GB00BS88V64",    # 11 characters
    "GB00BS88V6477",  # 13 characters
    "GB00BS88V64X",   # check digit must be a digit
])
def test_bad_isins_fail(isin):
    assert not isin_is_valid(isin)
