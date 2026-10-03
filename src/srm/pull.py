"""Pull raw snapshots for the Phase 1 source cards.

    python -m srm.pull [--missing-only] [card_id ...]

By default every entry is fetched again and archived only if its content changed since the
latest snapshot (monthly refresh). --missing-only fetches entries never archived before.
Each pull is independent: a failure is reported and the run continues.
"""

from __future__ import annotations

import sys
import time

from srm.snapshot import RAW_DIR, SnapshotError, fetch

ECB = "https://data-api.ecb.europa.eu/service/data"
ES = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
OECD = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0"
)
ES_FMT = "lang=en"
NATIONAL = "geo=EA&geo=DE&geo=FR&geo=IT&geo=ES&geo=EU27_2020"

# (card_id, label, url, kind)
PULLS: list[tuple[str, str, str, str]] = [
    (
        "ecb_icp",
        "hicp_headline_annual_rate",
        f"{ECB}/ICP/M.U2.N.000000.4.ANR?format=csvdata",
        "csv",
    ),
    (
        "ecb_icp",
        "hicp_core_xef_annual_rate",
        f"{ECB}/ICP/M.U2.N.XEF000.4.ANR?format=csvdata",
        "csv",
    ),
    (
        "ecb_hicp",
        "hicp_headline_annual_rate",
        f"{ECB}/HICP/M.U2.N.000000.4D0.ANR?format=csvdata",
        "csv",
    ),
    (
        "ecb_hicp",
        "hicp_core_xef000_annual_rate",
        f"{ECB}/HICP/M.U2.N.XEF000.4D0.ANR?format=csvdata",
        "csv",
    ),
    (
        "ecb_fm_policy_rates",
        "deposit_facility",
        f"{ECB}/FM/B.U2.EUR.4F.KR.DFR.LEV?format=csvdata",
        "csv",
    ),
    (
        "ecb_fm_policy_rates",
        "main_refinancing",
        f"{ECB}/FM/B.U2.EUR.4F.KR.MRR_FR.LEV?format=csvdata",
        "csv",
    ),
    ("ecb_yc", "spot_10y", f"{ECB}/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y?format=csvdata", "csv"),
    ("ecb_yc", "spot_2y", f"{ECB}/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y?format=csvdata", "csv"),
    (
        "ecb_rtd",
        "monthly_catalog_latest",
        f"{ECB}/RTD/M....?lastNObservations=1&format=csvdata",
        "csv",
    ),
    (
        "ecb_rtd",
        "hicp_annual_rate_all_vintages",
        f"{ECB}/RTD/M.S0.N.P_C_OV.A?includeHistory=true&format=csvdata",
        "csv",
    ),
    (
        "ecb_rtd",
        "unemployment_rate_all_vintages",
        f"{ECB}/RTD/M.S0.S.L_UNETO.F?includeHistory=true&format=csvdata",
        "csv",
    ),
    (
        "ecb_rtd",
        "hicp_energy_index_all_vintages",
        f"{ECB}/RTD/M.S0.N.P_C_NRGY.X?includeHistory=true&format=csvdata",
        "csv",
    ),
    (
        "ecb_rtd",
        "hicp_ex_energy_unprocessed_food_index_all_vintages",
        f"{ECB}/RTD/M.S0.N.P_C_XEFUN.X?includeHistory=true&format=csvdata",
        "csv",
    ),
    (
        "ecb_rtd",
        "gov_balance_pct_gdp_all_vintages",
        f"{ECB}/RTD/A.S0.N.F_UMD_CGG_D0.F?includeHistory=true&format=csvdata",
        "csv",
    ),
    (
        "ecb_rtd",
        "gov_primary_balance_pct_gdp_all_vintages",
        f"{ECB}/RTD/A.S0.N.F_UMS_CGG_D0.F?includeHistory=true&format=csvdata",
        "csv",
    ),
    (
        "eurostat_une_rt_m",
        "ea21_sa_total_pc_act",
        f"{ES}/une_rt_m?geo=EA21&s_adj=SA&age=TOTAL&unit=PC_ACT&sex=T&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_une_rt_m",
        "vintages_2021_on_ea",
        f"{ES}/ei_lm_m_vtg?geo=EA&unit=PC_ACT&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_une_rt_m",
        "vintages_2001_2020_ea",
        f"{ES}/ei_lm_m_vtgfix?geo=EA&unit=PC_ACT&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_namq_10_gdp",
        "ea_sca_b1gq_qoq",
        f"{ES}/namq_10_gdp?geo=EA&s_adj=SCA&na_item=B1GQ&unit=CLV_PCH_PRE&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_namq_10_gdp",
        "vintages_ea_sca",
        f"{ES}/ei_na_q_vtg?geo=EA&s_adj=SCA&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_sts_inpr_m",
        "ea21_sca_bd_i21",
        f"{ES}/sts_inpr_m?geo=EA21&s_adj=SCA&nace_r2=B-D&unit=I21&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_sts_inpr_m",
        "vintages_2021_on_ea_sca_i21",
        f"{ES}/ei_is_m_vtg?geo=EA&s_adj=SCA&unit=I21&{ES_FMT}",
        "json",
    ),
    ("eurostat_namq_10_lp_ulc", "ea_all", f"{ES}/namq_10_lp_ulc?geo=EA&{ES_FMT}", "json"),
    (
        "eurostat_gov_10dd_edpt1",
        "ea21_ea20_s13",
        f"{ES}/gov_10dd_edpt1?geo=EA21&geo=EA20&sector=S13&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_nrg_pc_205",
        "major_economies_eur",
        f"{ES}/nrg_pc_205?{NATIONAL}&currency=EUR&{ES_FMT}",
        "json",
    ),
    (
        "eurostat_nrg_pc_203",
        "major_economies_eur",
        f"{ES}/nrg_pc_203?{NATIONAL}&currency=EUR&{ES_FMT}",
        "json",
    ),
    (
        "oecd_mei_revisions",
        "ea20_monthly_cpi_since_2018",
        f"{OECD}/EA20.M.CP....?startPeriod=2018-01&format=csv",
        "csv",
    ),
    (
        "oecd_mei_revisions",
        "ea19_quarterly_ulc_since_2008",
        f"{OECD}/EA19.Q.ULC....?startPeriod=2008-Q1&format=csv",
        "csv",
    ),
    (
        "oecd_mei_revisions",
        "ea20_quarterly_ulc_since_2008",
        f"{OECD}/EA20.Q.ULC....?startPeriod=2008-Q1&format=csv",
        "csv",
    ),
    (
        "oecd_mei_revisions",
        "ea20_quarterly_gdp_since_2015",
        f"{OECD}/EA20.Q.B1GQ_Q....?startPeriod=2015-Q1&format=csv",
        "csv",
    ),
]


SLOW = {
    "unemployment_rate_all_vintages",
    "vintages_2021_on_ea_sca_i21",
}


def already_pulled(card_id: str, label: str) -> bool:
    return any((RAW_DIR / card_id).glob(f"*__{label}.*")) if (RAW_DIR / card_id).exists() else False


def pull(
    selected: list[str] | None = None, missing_only: bool = False, verbose: bool = True
) -> list[dict]:
    """Fetch the manifest. Returns one result per entry: new, unchanged, skipped or failed."""
    results = []
    for card_id, label, url, kind in PULLS:
        if selected and card_id not in selected:
            continue
        if missing_only and already_pulled(card_id, label):
            results.append({"card": card_id, "label": label, "status": "skipped"})
            continue
        started = time.time()
        try:
            snap = fetch(card_id, label, url, kind, timeout=420 if label in SLOW else 180)
            status = "unchanged" if snap.unchanged else "new"
            results.append(
                {
                    "card": card_id,
                    "label": label,
                    "status": status,
                    "bytes": snap.size,
                    "path": str(snap.path.relative_to(RAW_DIR.parents[1])),
                }
            )
        except SnapshotError as exc:
            results.append({"card": card_id, "label": label, "status": "failed", "error": str(exc)})
        if verbose:
            r = results[-1]
            print(f"{r['status']:<9} {card_id}/{label}  {time.time() - started:5.1f}s", flush=True)
        time.sleep(1)
    return results


def main(argv: list[str]) -> int:
    missing_only = "--missing-only" in argv
    cards = [a for a in argv if not a.startswith("--")]
    results = pull(cards or None, missing_only=missing_only)
    failed = [r for r in results if r["status"] == "failed"]
    print(
        f"done: {sum(r['status'] == 'new' for r in results)} new, "
        f"{sum(r['status'] == 'unchanged' for r in results)} unchanged, {len(failed)} failed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
