"""Region-driven, sourced constants. Every number carries its source so agents can cite it.

A deployment serves one region (one Habitat affiliate's market), chosen with KEYSTONE_REGION and described by
keystone/regions/<id>.json. Orange County is the reference region (verified 2026-10-31; sources cached under
data/raw/source_docs/). Other regions keep their data under data/<region_id>/ and artifacts/<region_id>/.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGION_ID = os.environ.get("KEYSTONE_REGION", "orange_county_ca")
REGION = json.loads((ROOT / "keystone" / "regions" / f"{REGION_ID}.json").read_text())
_DEFAULT = REGION_ID == "orange_county_ca"
DATA_RAW = ROOT / "data" / "raw" if _DEFAULT else ROOT / "data" / REGION_ID / "raw"
DATA = ROOT / "data" / "processed" if _DEFAULT else ROOT / "data" / REGION_ID / "processed"
ARTIFACTS = ROOT / "artifacts" if _DEFAULT else ROOT / "artifacts" / REGION_ID  # trained models + registry (shipped)
# Runtime state the product writes as it works: agent runs, skills, lessons, sandbox audit. Point KEYSTONE_STATE_DIR
# at a persistent disk in production; child processes (the stdio MCP server) inherit it, so tests stay isolated too.
STATE = Path(os.environ["KEYSTONE_STATE_DIR"]).resolve() if os.environ.get("KEYSTONE_STATE_DIR") else ARTIFACTS
for _d in (DATA_RAW, DATA, ARTIFACTS, STATE):
    _d.mkdir(parents=True, exist_ok=True)

OC_BBOX = tuple(REGION["bbox"])  # lon_min, lat_min, lon_max, lat_max (name kept for compatibility)
BBOX = OC_BBOX

SOURCES = {
    "hcd_2026": "https://www.hcd.ca.gov/sites/default/files/docs/grants-and-funding/income-limits-2026.pdf",
    "hud_home_2026": "https://www.huduser.gov/portal/datasets/home-datasets/files/HOME_IncomeLmts_State_CA_2026.pdf",
    "car_sept_2026": "https://www.car.org/aboutus/mediacenter/newsreleases/2026releases/sept2026sales",
    "sb4_hcd": "https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/aff-hsg-faith-higher-ed-sb-4.pdf",
    "terner_sb4": "https://github.com/Terner-Center/SB4-Analysis",
    "habitat_oc_quals": "https://habitatoc.org/review-qualifications",
    "habitat_oc_myths": "https://habitatoc.org/myths-facts/",
    "keys_to_100": "https://habitatoc.org/keys-to-100-raises-330000-for-affordable-homeownership-in-orange-county/",
    "boe_214_15": "https://www.boe.ca.gov/proptaxes/pdf/lta23044.pdf",
    "cdi_fair_2026": "https://www.insurance.ca.gov/0200-industry/0105-alert/upload/FAIR-Plan-growth-slows-below-2-as-Californias-insurance-market-continues-to-show-signs-of-recovery.pdf",
    "rhna_progress": "https://data.ca.gov/dataset/rhna-progress-report",
    "hmda": "https://ffiec.cfpb.gov/data-browser/",
    "naip": "https://planetarycomputer.microsoft.com/dataset/naip",
    "oc_parcels": REGION["parcel_service"]["url"],
    "osm": "https://www.openstreetmap.org/copyright",
    "fuster_willen_2017": "https://doi.org/10.1257/pol.20150007",
    "ganong_noel_2020": "https://doi.org/10.1257/aer.20181243",
    "ge_johnson_tzur_ilan": "https://doi.org/10.24149/wp2505r1",
    "tian_quercia_riley_2016": "https://doi.org/10.1007/s11146-015-9501-8",
    "thaden_2011": "https://www.lincolninst.edu/publications/working-papers/stable-home-ownership-turbulent-economy/",
}

# CA HCD 2026 State Income Limits, Orange County (4-person unless noted)
OC_AMI_4P = REGION["ami_4p"]
INCOME_LIMITS_4P = REGION["income_limits_4p"]  # extremely_low, very_low (50%), low (80%), moderate (120%)
# HUD FY2026 HOME limits, Santa Ana-Anaheim-Irvine HMFA, scaled by household size (HUD standard adjustments)
HH_SIZE_ADJ = {1: 0.70, 2: 0.80, 3: 0.90, 4: 1.00, 5: 1.08, 6: 1.16, 7: 1.24, 8: 1.32}

OC_MEDIAN_SFH_PRICE = REGION["median_home_price"]
MARKET_30Y_RATE = REGION["market_30y_rate"]
HABITAT_PAYMENT_CAP = 0.30        # Habitat International; Habitat OC states ~30-35%
HABITAT_DOWN_PAYMENT = (0.01, 0.05)

# SB 4 (Gov. Code 65913.16) — OC is a metropolitan county
SB4_DENSITY_RESIDENTIAL_ZONE = REGION["faith_land_law"]["density_residential_zone"]   # du/acre
SB4_DENSITY_NONRES_ZONE = REGION["faith_land_law"]["density_nonresidential_zone"]
SB4_OWNERSHIP_DEED_YEARS = REGION["faith_land_law"]["ownership_deed_years"]
# Practical yield for Habitat-style for-sale townhomes (assumption, tunable by agents)
TOWNHOME_DU_PER_ACRE = 16
SQM_PER_ACRE = 4046.86

# Terner Center SB4 analysis, Orange County row (Table 1A)
_b = REGION.get("benchmark", {})
TERNER_OC = {"developable_acres": _b.get("developable_faith_acres"), "parcels": _b.get("faith_parcels"),
             "median_parcel_acres": _b.get("median_parcel_acres")}

# Default cost assumptions for an OC Habitat townhome (assumptions; agents flag them as such)
COST_ASSUMPTIONS = {
    "hard_cost_per_sqft": 375.0,
    "unit_sqft": 1_250,
    "soft_cost_share": 0.25,
    "volunteer_labor_savings": 0.08,
    "insurance_annual": 2_400.0,
    "insurance_annual_growth": 0.08,
    "hoa_monthly": 250.0,
    "maintenance_share_of_value": 0.01,
    "property_tax_rate": REGION["property_tax_rate"],
}
