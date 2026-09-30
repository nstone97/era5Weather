# ERA5 wave climatology (Gulf of Mexico)

Repository: [github.com/nstone97/era5Weather](https://github.com/nstone97/era5Weather)

Hourly ECMWF ERA5 reanalysis at one offshore point south of the Mississippi River Delta. The notebook pulls significant wave height plus 10 m wind, converts to feet and knots, and builds **one exceedance table per calendar month**. Each cell is the percent of hours when significant wave height **or** 10 m sustained wind exceeds that cell’s thresholds.

Primary interface is a **Flask web app**. The notebook is still there for one-off work.

```bash
cd /home/nstone/src/wavedata
source .venv/bin/activate
python app.py
```

Then open http://127.0.0.1:5000. The app loads the cached ERA5 extract, lets you change wave/wind thresholds, shows one table per month, and can pull a new CDS zip in the background.

Working notebook: [`wavedata.ipynb`](wavedata.ipynb). Figure: [`monthly_wave_wind_exceedance.png`](monthly_wave_wind_exceedance.png).

## Location

| | |
|---|---|
| Requested point | **28.662°N, 89.551°W** |
| Wave grid (0.5°) | 28.5°N, 89.5°W |
| Atmosphere grid (0.25°) | 28.75°N, 89.5°W |
| Period | hourly, **1940-01-01 00:00 through 2026-09-11 23:00** |
| Steps | 759,984 hours (~86.7 years) |

CDS nearest-neighbor extraction lands wave and atmosphere on **different** grid points. They share `valid_time` only.

## Data source

[Copernicus Climate Data Store](https://cds.climate.copernicus.eu/) dataset `reanalysis-era5-single-levels-timeseries`.

| CDS variable | Short name | Native units | Native grid |
|---|---|---|---|
| Significant height of combined wind waves and swell | `swh` | metres | 0.5° wave |
| 10 m U wind component | `u10` | m s⁻¹ | 0.25° atmosphere |
| 10 m V wind component | `v10` | m s⁻¹ | 0.25° atmosphere |
| 10 m wind gust since previous post-processing | `fg10` | m s⁻¹ | 0.25° atmosphere |

`fg10` is missing for all 24 hours of **1940-01-01** (ERA5 gusts start the next day). `swh`, `u10`, and `v10` are complete.

A CDS retrieve returns a zip of two NetCDFs (wave vs surface). Put credentials in `~/.cdsapirc` (Windows: `C:\Users\<you>\.cdsapirc`) or `CDSAPI_KEY` — do not commit keys.

If Windows Python raises `CERTIFICATE_VERIFY_FAILED` / `self-signed certificate in certificate chain`, a proxy or antivirus is intercepting HTTPS. Either:

```text
url: https://cds.climate.copernicus.eu/api
key: your-key
verify: 0
```

or, better, teach Python to use the Windows cert store:

```bat
pip install pip-system-certs
```

## Notebook flow

1. **Retrieve** — cell 0 asks `Download latest ERA5 timeseries from CDS? [y/N]`. Yes hits CDS and saves `era5-timeseries.zip`. No (the default) reuses that file, or the newest `*.zip` if it does not exist yet. Set `DOWNLOAD_LATEST = True` or `False` in the cell to skip the prompt.
2. **Extract** — unzip into `tmp/`, open:
   - `waveds` from `*wav*.nc` (`swh`)
   - `sfcds` from `*sfc*.nc` (`u10`, `v10`, `fg10`)
3. **Join on time** — drop lat/lon, then:

   ```python
   df = (
       waveds.to_dataframe()[["swh"]]
       .join(sfcds.to_dataframe()[["u10", "v10", "fg10"]])
   )
   ```

   Do **not** `xr.merge` the two Datasets. Default merge raises `MergeError` on `latitude` (28.5 vs 28.75). `compat="override"` would keep the first dataset’s coords and hide the mismatch.

4. **Unit conversion** (in place on `df`):
   - `swh`: metres → feet (`× 3.28084`)
   - `s10`: 10 m wind speed from `hypot(u10, v10)`, m s⁻¹ → knots (`× 1.943844`)
   - `fg10`: m s⁻¹ → knots (`× 1.943844`)
   - `u10` / `v10` stay in m s⁻¹ (components used only to build `s10`)
5. **Exceedance** — drop hours with missing `swh` or `s10`, group by calendar month. One table per month:
   - rows: wave height 0, 2, …, 16 ft (2 ft steps)
   - columns: sustained 10 m wind 0, 5, …, 35 kt (5 kt steps)
   - cell: percent of hours with `swh > row` **or** `s10 > column`
6. **Export** — 12 HTML tables in the notebook, plus a 4×3 figure saved as `monthly_wave_wind_exceedance.png`.

After conversion, `df` is indexed by `valid_time` with columns `swh` (ft), `u10` (m s⁻¹), `v10` (m s⁻¹), `fg10` (kt), `s10` (kt).

## Results (this extract)

Mean significant wave height is about **3.2 ft** (median ~2.6 ft). Mean 10 m wind is ~11 kt. The 0 ft / 0 kt edges of each table are 100% (every hour has some wave height and some wind). Columns at 5–10 kt are still high; the union is more informative from about 15 kt up.

Winter months are the roughest at moderate thresholds. July–August are the calmest. **September** stands out at the high-wind / high-wave corner (tropical-cyclone season): e.g. ~19% of September hours have waves above 4 ft or wind above 20 kt, versus ~3.5% in July.

## Files

| Path | Role |
|---|---|
| `app.py` | Flask app: dashboard + JSON/CSV API |
| `analysis.py` | ERA5 load, unit conversion, exceedance math |
| `templates/`, `static/` | Frontend |
| `wavedata.ipynb` | Same pipeline as a notebook |
| `monthly_wave_wind_exceedance.png` | 12 monthly wave-or-wind exceedance tables |
| `era5-timeseries.zip` | Cached CDS download (created on a yes-download) |
| `*.zip` | Older hash-named CDS downloads, used if the cached name is missing |
| `tmp/*wav*.nc`, `tmp/*sfc*.nc` | Extracted NetCDFs |
| `.venv/` | Local Python env (`cdsapi`, `xarray`, `pandas`, `netCDF4`, `matplotlib`) |
| `test.py` | Empty placeholder |

## How to rerun

```bash
cd /home/nstone/src/wavedata
source .venv/bin/activate
jupyter notebook wavedata.ipynb
```

Run cell 0 and answer **n** to reuse the last zip, or **y** to retrieve again (date window is in the request dict). Cells 1–4 then extract that zip into `tmp/` and continue.
