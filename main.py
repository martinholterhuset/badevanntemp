import csv
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv  # pip install python-dotenv

load_dotenv()
NVE_API_KEY = os.environ["NVE_API_KEY"].strip()

PARAMETER_VANNTEMP = 1003
HEADERS_NVE = {"X-API-Key": NVE_API_KEY, "Accept": "application/json"}

# Bounding box rundt Romerike/Øyeren (lat/lon, WGS84). Brukes til å filtrere
# Yr-badeplasser geografisk. Samme boks som i søkescriptet.
LAT_MIN, LAT_MAX = 59.7, 60.5
LON_MIN, LON_MAX = 10.8, 11.7

# Valgfri ekstra navnefiltrering for Yr. Tom liste = ingen navnefiltrering
# (kun geofilteret over gjelder da).
YR_BADEPLASSER = []  # f.eks. ["Nordre Øyeren", "Sognsvann"]

# NVE-stasjoner med bekreftet ferske vanntemperaturdata.
NVE_STASJONER = [
    ("2.587.0", "Glomma v/Fetsund bru"),
    ("2.17.0", "Glomma v/Blaker"),
    ("2.1211.0", "Langvatnet"),
    ("2.1213.0", "Mønevann"),
    ("2.470.0", "Storsjøen i Odalen"),
    ("2.1248.0", "Tisjøen"),
    ("2.1227.0", "Ellingsjøen"),
]


def innenfor_omrade(lat, lon):
    if lat is None or lon is None:
        return False
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def hent_yr():
    """Henter badetemperaturer fra Yrs uoffisielle endepunkt, filtrert til området."""
    url = "https://www.yr.no/api/v0/regions/NO/watertemperatures"
    r = requests.get(
        url,
        headers={"User-Agent": "romerikesblad badetemp martin.holterhuset@rb.no"},
        timeout=30,
    )
    r.raise_for_status()
    rader = []
    for st in r.json():
        navn = st.get("location", {}).get("name", "")
        pos = st.get("location", {}).get("position", {})
        lat, lon = pos.get("lat"), pos.get("lon")

        # Geofilter: kun badeplasser innenfor bounding-boxen
        if not innenfor_omrade(lat, lon):
            continue
        # Valgfritt navnefilter på toppen
        if YR_BADEPLASSER and navn not in YR_BADEPLASSER:
            continue

        rader.append(
            {
                "sted": navn,
                "temperatur": st.get("temperature"),
                "tid": st.get("time"),
                "lat": lat,
                "lon": lon,
                "kilde": "Yr",
            }
        )
    return rader


def hent_nve_siste(stasjon_id):
    """Nyeste døgnobservasjon (verdi, tid) for vanntemperatur, ellers (None, None)."""
    r = requests.get(
        "https://hydapi.nve.no/api/v1/Observations",
        params={
            "StationId": stasjon_id,
            "Parameter": PARAMETER_VANNTEMP,
            "ResolutionTime": "day",
            "ReferenceTime": "P30D/",
        },
        headers=HEADERS_NVE,
        timeout=60,
    )
    r.raise_for_status()
    for serie in r.json().get("data", []):
        gyldige = [o for o in serie.get("observations", []) if o.get("value") is not None]
        if gyldige:
            siste = max(gyldige, key=lambda o: o.get("time", ""))
            return siste.get("value"), siste.get("time")
    return None, None


def hent_nve_stasjonsinfo():
    """{stationId: (lat, lon)} for å berike NVE-radene med koordinater."""
    r = requests.get(
        "https://hydapi.nve.no/api/v1/Stations",
        params={"Active": 1},
        headers=HEADERS_NVE,
        timeout=60,
    )
    r.raise_for_status()
    return {
        st["stationId"]: (st.get("latitude"), st.get("longitude"))
        for st in r.json().get("data", [])
    }


def hent_nve():
    info = hent_nve_stasjonsinfo()
    rader = []
    for stasjon_id, navn in NVE_STASJONER:
        verdi, tid = hent_nve_siste(stasjon_id)
        if verdi is None:
            continue
        lat, lon = info.get(stasjon_id, (None, None))
        rader.append(
            {
                "sted": navn,
                "temperatur": round(verdi, 1),
                "tid": tid,
                "lat": lat,
                "lon": lon,
                "kilde": "NVE",
            }
        )
    return rader


def main():
    rader = hent_yr() + hent_nve()

    felter = ["sted", "temperatur", "tid", "lat", "lon", "kilde"]
    with open("badetemp.csv", "w", newline="", encoding="utf-8") as f:
        skriver = csv.DictWriter(f, fieldnames=felter)
        skriver.writeheader()
        skriver.writerows(rader)

    yr_ant = sum(1 for r in rader if r["kilde"] == "Yr")
    nve_ant = sum(1 for r in rader if r["kilde"] == "NVE")
    print(
        f"Skrev {len(rader)} rader til badetemp.csv "
        f"(Yr: {yr_ant}, NVE: {nve_ant}) "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    )


if __name__ == "__main__":
    main()