"""Offline tests for the contracts scraper parse and salary joins."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import (
    attach_salary,
    player_contract,
    salary_seasons,
    team_contracts,
    team_payroll,
)
from nba_insights.analysis.salaries import normalize_name
from nba_insights.ingest.salaries import parse_contracts

# mimics the real page: two-level header, repeated header row in the body,
# $-formatted money, blanks for expired years, B-Ref tricodes (BRK)
PAGE = """
<table>
<thead>
<tr><th></th><th></th><th></th><th colspan="2">Salary</th><th></th></tr>
<tr><th>Rk</th><th>Player</th><th>Tm</th><th>2026-27</th><th>2027-28</th><th>Guaranteed</th></tr>
</thead>
<tbody>
<tr><td>1</td><td>Nikola Jokić</td><td>DEN</td>
<td>$59,033,114</td><td>$62,841,702</td><td>$59,033,114</td></tr>
<tr><td>2</td><td>Big Spender Jr.</td><td>BRK</td>
<td>$10,000,000</td><td></td><td>$10,000,000</td></tr>
<tr><td>Rk</td><td>Player</td><td>Tm</td><td>2026-27</td><td>2027-28</td><td>Guaranteed</td></tr>
<tr><td>3</td><td>Cheap Guy</td><td>BRK</td>
<td>$2,000,000</td><td>$2,100,000</td><td>$4,100,000</td></tr>
</tbody>
</table>
"""


def test_parse_contracts_shapes_and_money():
    out = parse_contracts(PAGE)
    assert list(out["PLAYER_NAME"]) == ["Nikola Jokić", "Big Spender Jr.", "Cheap Guy"]
    assert salary_seasons(out) == ["2026-27", "2027-28"]
    assert out.loc[0, "2026-27"] == 59033114.0
    assert pd.isna(out.loc[1, "2027-28"])  # expired year stays NaN
    assert out.loc[2, "GUARANTEED"] == 4100000.0
    assert set(out["TEAM_ABBREVIATION"]) == {"DEN", "BKN"}  # BRK fixed to BKN


def test_parse_contracts_rejects_unrecognized_page():
    with pytest.raises(ValueError):
        parse_contracts("<html><body>Rate limited</body></html>")
    with pytest.raises(ValueError):
        parse_contracts("<table><tr><th>Foo</th></tr><tr><td>1</td></tr></table>")


def test_normalize_name_folds_sources_together():
    assert normalize_name("Nikola Jokić") == normalize_name("Nikola Jokic")
    assert normalize_name("Jaren Jackson Jr.") == normalize_name("Jaren Jackson")
    assert normalize_name("De'Aaron Fox") == normalize_name("DeAaron Fox")


def test_attach_salary_joins_by_normalized_name():
    contracts = parse_contracts(PAGE)
    league = pd.DataFrame(
        {
            "PLAYER_NAME": ["Nikola Jokic", "Big Spender", "Nobody"],  # no diacritic, no Jr.
            "PTS": [27.0, 10.0, 5.0],
        }
    )
    out = attach_salary(league, contracts)
    assert len(out) == 3  # nobody dropped
    assert out.loc[0, "SALARY"] == 59033114.0
    assert out.loc[1, "SALARY"] == 10000000.0
    assert pd.isna(out.loc[2, "SALARY"])
    assert out.loc[0, "GUARANTEED"] == 59033114.0
    with pytest.raises(KeyError, match="PLAYER_NAME"):
        attach_salary(league.drop(columns=["PLAYER_NAME"]), contracts)


def test_team_payroll_sums_nearest_season():
    payroll = team_payroll(parse_contracts(PAGE))
    assert payroll["DEN"] == 59033114.0
    assert payroll["BKN"] == 12000000.0
    assert payroll.index[0] == "DEN"  # largest first


def test_player_contract_looks_up_by_normalized_name():
    contracts = parse_contracts(PAGE)
    row = player_contract(contracts, "Nikola Jokic")  # no diacritic
    assert row["2026-27"] == 59033114.0
    assert row["GUARANTEED"] == 59033114.0
    with pytest.raises(KeyError, match="Nobody"):
        player_contract(contracts, "Nobody")


def test_team_contracts_sorts_book_by_nearest_season():
    book = team_contracts(parse_contracts(PAGE), "BKN")
    assert list(book["PLAYER_NAME"]) == ["Big Spender Jr.", "Cheap Guy"]  # largest first
    assert book.loc[1, "2027-28"] == 2100000.0
    assert "GUARANTEED" in book.columns
    assert team_contracts(parse_contracts(PAGE), "LAL").empty
    with pytest.raises(KeyError):
        team_contracts(parse_contracts(PAGE).drop(columns=["TEAM_ABBREVIATION"]), "BKN")
