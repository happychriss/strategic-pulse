"""Pull the first raw snapshots for Phase 1 source cards.

Usage: python scripts/pull_phase1.py [card_id ...]
Each pull is independent: a failure is reported and the run continues.
Phase 0 proof-of-access slices are deliberately narrow; full histories come with the schema.
"""

from __future__ import annotations

import sys
import time

from srm.snapshot import SnapshotError, fetch

ECB = "https://data-api.ecb.europa.eu/service/data"
ES = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
OECD = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0"
)
ES_FMT = "format=SDMX-CSV&lang=en"
NATIONAL = "geo=DE&geo=FR&geo=IT&geo=ES&geo=EU27_2020"

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
        "eurostat_une_rt_m",
        "ea20_sa_total_pc_act",
        f"{ES}/une_rt_m?geo=EA20&s_adj=SA&age=TOTAL&unit=PC_ACT&sex=T&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_une_rt_m",
        "vintages_2021_on_ea",
        f"{ES}/ei_lm_m_vtg?geo=EA&unit=PC_ACT&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_une_rt_m",
        "vintages_2001_2020_ea",
        f"{ES}/ei_lm_m_vtgfix?geo=EA&unit=PC_ACT&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_namq_10_gdp",
        "ea20_sca_b1gq_qoq",
        f"{ES}/namq_10_gdp?geo=EA20&s_adj=SCA&na_item=B1GQ&unit=CLV_PCH_PRE&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_namq_10_gdp",
        "vintages_ea_sca",
        f"{ES}/ei_na_q_vtg?geo=EA&s_adj=SCA&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_sts_inpr_m",
        "ea20_sca_bd_i21",
        f"{ES}/sts_inpr_m?geo=EA20&s_adj=SCA&nace_r2=B-D&unit=I21&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_sts_inpr_m",
        "vintages_2021_on_ea_sca_i21",
        f"{ES}/ei_is_m_vtg?geo=EA&s_adj=SCA&unit=I21&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_sts_inpr_m",
        "vintages_2001_2020_ea_sca",
        f"{ES}/ei_is_m_vtgfix?geo=EA&s_adj=SCA&{ES_FMT}",
        "csv",
    ),
    ("eurostat_namq_10_lp_ulc", "ea20_all", f"{ES}/namq_10_lp_ulc?geo=EA20&{ES_FMT}", "csv"),
    (
        "eurostat_gov_10dd_edpt1",
        "ea20_s13",
        f"{ES}/gov_10dd_edpt1?geo=EA20&sector=S13&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_nrg_pc_205",
        "major_economies_eur",
        f"{ES}/nrg_pc_205?{NATIONAL}&currency=EUR&{ES_FMT}",
        "csv",
    ),
    (
        "eurostat_nrg_pc_203",
        "major_economies_eur",
        f"{ES}/nrg_pc_203?{NATIONAL}&currency=EUR&{ES_FMT}",
        "csv",
    ),
    (
        "oecd_mei_revisions",
        "ea20_monthly_cpi_since_2018",
        f"{OECD}/EA20.M.CP....?startPeriod=2018-01&format=csv",
        "csv",
    ),
    (
        "oecd_mei_revisions",
        "ea20_quarterly_gdp_since_2015",
        f"{OECD}/EA20.Q.B1GQ_Q....?startPeriod=2015-Q1&format=csv",
        "csv",
    ),
]


def main(selected: list[str]) -> int:
    failures = 0
    for card_id, label, url, kind in PULLS:
        if selected and card_id not in selected:
            continue
        started = time.time()
        try:
            snap = fetch(card_id, label, url, kind)
            print(
                f"OK   {card_id}/{label}  {snap.size:>10,} B  {time.time() - started:5.1f}s",
                flush=True,
            )
        except SnapshotError as exc:
            failures += 1
            print(f"FAIL {card_id}/{label}  {exc}", flush=True)
        time.sleep(1)
    print(f"done, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
