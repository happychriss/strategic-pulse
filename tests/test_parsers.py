from decimal import Decimal as D

from srm.parsers import parse_ecb_csv, parse_eurostat_jsonstat, parse_oecd_csv
from srm.snapshot import RAW_DIR


def one(pattern):
    return max(RAW_DIR.glob(pattern))


def test_eurostat_vintage_table_yields_revdates():
    pts = list(parse_eurostat_jsonstat(one("eurostat_une_rt_m/*vintages_2021_on_ea.json")))
    p = next(p for p in pts if p.period_label == "2016-03" and p.vintage == "2021-01-08")
    assert p.value == D("10.2")
    assert p.region_src == "EA" and "revdate" not in p.dims and "time" not in p.dims


def test_ecb_history_contains_withdrawals_and_timestamps():
    pts = list(parse_ecb_csv(one("ecb_rtd/*hicp_annual_rate_all_vintages.csv")))
    assert any(p.withdrawn for p in pts)
    live = [p for p in pts if not p.withdrawn]
    assert all("T" in p.vintage for p in live)


def test_ecb_plain_csv_has_no_vintage():
    pts = list(parse_ecb_csv(one("ecb_hicp/*headline*.csv")))
    assert pts and all(p.vintage is None for p in pts)
    assert pts[0].series_key.startswith("HICP.M.U2")


def test_oecd_edition_is_vintage_and_base_period_is_an_attribute():
    pts = list(parse_oecd_csv(one("oecd_mei_revisions/*cpi*.csv")))
    p = pts[0]
    assert len(p.vintage) == 6 and "EDITION" not in p.dims
    assert p.attrs and "BASE_PER" in p.attrs
