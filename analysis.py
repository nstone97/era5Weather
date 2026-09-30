"""Load ERA5 timeseries and compute monthly wave-or-wind exceedance."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parent
TMP_DIR = ROOT / "tmp"
LOCAL_ZIP = ROOT / "era5-timeseries.zip"

M_TO_FT = 3.28084
MS_TO_KT = 1.943844

REQUEST_LATITUDE = 28.662
REQUEST_LONGITUDE = -89.551
CDS_DATASET = "reanalysis-era5-single-levels-timeseries"
CDS_URL = os.environ.get("CDSAPI_URL", "https://cds.climate.copernicus.eu/api")

_lock = threading.Lock()
_catalog = None
_refresh = {"status": "idle", "message": ""}


@dataclass
class Catalog:
    hours: pd.DataFrame
    wave_latitude: float
    wave_longitude: float
    surface_latitude: float
    surface_longitude: float
    source: str
    request_latitude: float = REQUEST_LATITUDE
    request_longitude: float = REQUEST_LONGITUDE


def find_zip() -> Path:
    if LOCAL_ZIP.exists():
        return LOCAL_ZIP
    zips = sorted(ROOT.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not zips:
        raise FileNotFoundError(
            "No local ERA5 zip found. Download from CDS first."
        )
    return zips[0]


def _open_pair_from_tmp() -> tuple[xr.Dataset | None, xr.Dataset | None]:
    if not TMP_DIR.exists():
        return None, None
    wave_files = sorted(TMP_DIR.glob("*wav*.nc"))
    sfc_files = sorted(TMP_DIR.glob("*sfc*.nc"))
    if not wave_files or not sfc_files:
        return None, None
    waveds = xr.open_dataset(wave_files[-1], engine="netcdf4")
    sfcds = xr.open_dataset(sfc_files[-1], engine="netcdf4")
    return waveds, sfcds


def extract_pair(zip_path: Path) -> tuple[xr.Dataset, xr.Dataset]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    waveds = sfcds = None
    with ZipFile(zip_path) as archive:
        archive.extractall(TMP_DIR)
        for name in archive.namelist():
            if re.match(r"^.+wav.+\.nc$", name):
                waveds = xr.open_dataset(TMP_DIR / name, engine="netcdf4")
            if re.match(r"^.+sfc.+\.nc$", name):
                sfcds = xr.open_dataset(TMP_DIR / name, engine="netcdf4")
    if waveds is None or sfcds is None:
        raise FileNotFoundError(f"Zip {zip_path} did not contain wave and surface NetCDFs.")
    return waveds, sfcds


def _as_datetime_index(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.index, pd.MultiIndex):
        time_level = "valid_time" if "valid_time" in frame.index.names else frame.index.names[0]
        timestamps = pd.to_datetime(frame.index.get_level_values(time_level))
    else:
        timestamps = pd.to_datetime(frame.index)
    out = frame.copy()
    out.index = timestamps
    out.index.name = "valid_time"
    return out


def build_hours(waveds: xr.Dataset, sfcds: xr.Dataset) -> pd.DataFrame:
    frame = (
        waveds.to_dataframe()[["swh"]]
        .join(sfcds.to_dataframe()[["u10", "v10", "fg10"]])
    )
    frame = _as_datetime_index(frame)
    frame["s10"] = (frame["u10"] ** 2 + frame["v10"] ** 2) ** 0.5 * MS_TO_KT
    frame["fg10"] = frame["fg10"].astype("float") * MS_TO_KT
    frame["swh"] = frame["swh"].astype("float") * M_TO_FT
    return frame


def load_catalog(force_extract: bool = False) -> Catalog:
    waveds = sfcds = None
    source = None
    if not force_extract:
        waveds, sfcds = _open_pair_from_tmp()
        if waveds is not None:
            source = "tmp"
    if waveds is None or sfcds is None:
        zip_path = find_zip()
        waveds, sfcds = extract_pair(zip_path)
        source = zip_path.name
    hours = build_hours(waveds, sfcds)
    catalog = Catalog(
        hours=hours,
        wave_latitude=float(waveds.latitude),
        wave_longitude=float(waveds.longitude),
        surface_latitude=float(sfcds.latitude),
        surface_longitude=float(sfcds.longitude),
        source=source,
    )
    waveds.close()
    sfcds.close()
    return catalog


def get_catalog() -> Catalog:
    global _catalog
    with _lock:
        if _catalog is None:
            _catalog = load_catalog()
        return _catalog


def replace_catalog(catalog: Catalog) -> None:
    global _catalog
    with _lock:
        _catalog = catalog


def refresh_status() -> dict:
    with _lock:
        return dict(_refresh)


def _set_refresh(status: str, message: str = "") -> None:
    with _lock:
        _refresh["status"] = status
        _refresh["message"] = message


def thresholds(max_value: float, step: float) -> list[int]:
    if step <= 0:
        raise ValueError("step must be positive")
    if max_value < 0:
        raise ValueError("max must be at least 0")
    values = []
    current = 0.0
    while current <= max_value + 1e-9:
        values.append(int(round(current)))
        current += step
    return values


def monthly_exceedance(
    hours: pd.DataFrame,
    wave_max: int = 16,
    wave_step: int = 2,
    wind_max: int = 35,
    wind_step: int = 5,
) -> dict:
    wave_levels = thresholds(wave_max, wave_step)
    wind_levels = thresholds(wind_max, wind_step)
    work = hours[["swh", "s10"]].dropna()
    month_names = [datetime(2024, month, 1).strftime("%b") for month in range(1, 13)]
    wave_arr = np.asarray(wave_levels)[None, :, None]
    wind_arr = np.asarray(wind_levels)[None, None, :]
    tables = {}
    counts = {}
    for month, name in enumerate(month_names, start=1):
        month_hours = work[work.index.month == month]
        counts[name] = int(len(month_hours))
        if month_hours.empty:
            tables[name] = np.full((len(wave_levels), len(wind_levels)), np.nan).tolist()
            continue
        swh = month_hours["swh"].to_numpy()[:, None, None]
        s10 = month_hours["s10"].to_numpy()[:, None, None]
        pct = ((swh > wave_arr) | (s10 > wind_arr)).mean(axis=0) * 100.0
        tables[name] = np.round(pct, 2).tolist()
    return {
        "wave_thresholds": wave_levels,
        "wind_thresholds": wind_levels,
        "months": tables,
        "hours_by_month": counts,
    }


def summarize(hours: pd.DataFrame) -> dict:
    work = hours[["swh", "s10"]].dropna()
    swh = work["swh"]
    s10 = work["s10"]
    return {
        "hours": int(len(work)),
        "start": work.index.min().strftime("%Y-%m-%d %H:%M"),
        "end": work.index.max().strftime("%Y-%m-%d %H:%M"),
        "swh_mean_ft": round(float(swh.mean()), 2),
        "swh_median_ft": round(float(swh.median()), 2),
        "swh_p99_ft": round(float(swh.quantile(0.99)), 2),
        "swh_max_ft": round(float(swh.max()), 2),
        "s10_mean_kt": round(float(s10.mean()), 2),
        "s10_p99_kt": round(float(s10.quantile(0.99)), 2),
        "s10_max_kt": round(float(s10.max()), 2),
    }


def catalog_status(catalog: Catalog) -> dict:
    summary = summarize(catalog.hours)
    return {
        **summary,
        "request_latitude": catalog.request_latitude,
        "request_longitude": catalog.request_longitude,
        "wave_latitude": catalog.wave_latitude,
        "wave_longitude": catalog.wave_longitude,
        "surface_latitude": catalog.surface_latitude,
        "surface_longitude": catalog.surface_longitude,
        "source": catalog.source,
        "refresh": refresh_status(),
    }


def _cds_verify() -> bool:
    env = os.environ.get("CDSAPI_VERIFY")
    if env is not None:
        return env.strip().lower() not in {"0", "false", "no"}
    rc_path = Path(os.environ.get("CDSAPI_RC", Path.home() / ".cdsapirc"))
    if rc_path.exists():
        for line in rc_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("verify:"):
                return bool(int(line.split(":", 1)[1].strip()))
    return True


def _cds_client():
    import cdsapi

    verify = _cds_verify()
    key = os.environ.get("CDSAPI_KEY")
    if key:
        return cdsapi.Client(url=CDS_URL, key=key, verify=verify)
    return cdsapi.Client(verify=verify)


def download_era5(
    latitude: float,
    longitude: float,
    date_start: str,
    date_end: str,
) -> Path:
    client = _cds_client()
    request = {
        "variable": [
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
            "10m_wind_gust_since_previous_post_processing",
            "significant_height_of_combined_wind_waves_and_swell",
        ],
        "location": {"longitude": longitude, "latitude": latitude},
        "date": [f"{date_start}/{date_end}"],
        "data_format": "netcdf",
    }
    client.retrieve(CDS_DATASET, request).download(str(LOCAL_ZIP))
    return LOCAL_ZIP


def refresh_catalog(
    latitude: float = REQUEST_LATITUDE,
    longitude: float = REQUEST_LONGITUDE,
    date_start: str = "1940-01-01",
    date_end: str | None = None,
) -> None:
    if date_end is None:
        date_end = date.today().isoformat()
    _set_refresh("running", "Requesting ERA5 timeseries from CDS…")
    try:
        download_era5(latitude, longitude, date_start, date_end)
        _set_refresh("running", "Extracting NetCDFs…")
        catalog = load_catalog(force_extract=True)
        catalog.request_latitude = latitude
        catalog.request_longitude = longitude
        replace_catalog(catalog)
        _set_refresh("ready", f"Loaded {len(catalog.hours):,} hours.")
    except Exception as exc:
        _set_refresh("error", str(exc))
        raise


def start_refresh(**kwargs) -> dict:
    status = refresh_status()
    if status["status"] == "running":
        return status

    def worker():
        try:
            refresh_catalog(**kwargs)
        except Exception:
            pass

    _set_refresh("running", "Starting CDS retrieve…")
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return refresh_status()
