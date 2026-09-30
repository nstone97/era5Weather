from __future__ import annotations

import csv
import io

from flask import Flask, Response, jsonify, render_template, request

import analysis
import pdf_report

app = Flask(__name__)
app.json.sort_keys = False


def _threshold_args():
    wave_max = int(request.args.get("wave_max", 16))
    wave_step = int(request.args.get("wave_step", 2))
    wind_max = int(request.args.get("wind_max", 35))
    wind_step = int(request.args.get("wind_step", 5))
    if wave_max > 40 or wind_max > 80:
        raise ValueError("Thresholds are too large.")
    if wave_step < 1 or wind_step < 1:
        raise ValueError("Steps must be at least 1.")
    return wave_max, wave_step, wind_max, wind_step


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    try:
        catalog = analysis.get_catalog()
        return jsonify(analysis.catalog_status(catalog))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc), "refresh": analysis.refresh_status()}), 404


@app.get("/api/exceedance")
def exceedance():
    try:
        wave_max, wave_step, wind_max, wind_step = _threshold_args()
        catalog = analysis.get_catalog()
        payload = analysis.monthly_exceedance(
            catalog.hours,
            wave_max=wave_max,
            wave_step=wave_step,
            wind_max=wind_max,
            wind_step=wind_step,
        )
        payload["status"] = analysis.catalog_status(catalog)
        return jsonify(payload)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/exceedance.csv")
def exceedance_csv():
    wave_max, wave_step, wind_max, wind_step = _threshold_args()
    catalog = analysis.get_catalog()
    payload = analysis.monthly_exceedance(
        catalog.hours,
        wave_max=wave_max,
        wave_step=wave_step,
        wind_max=wind_max,
        wind_step=wind_step,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["month", "wave_ft", "wind_kt", "exceedance_pct"])
    for month, table in payload["months"].items():
        for row_index, wave in enumerate(payload["wave_thresholds"]):
            for col_index, wind in enumerate(payload["wind_thresholds"]):
                writer.writerow([month, wave, wind, table[row_index][col_index]])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=monthly_exceedance.csv"},
    )


@app.get("/api/exceedance.pdf")
def exceedance_pdf():
    try:
        wave_max, wave_step, wind_max, wind_step = _threshold_args()
        catalog = analysis.get_catalog()
        payload = analysis.monthly_exceedance(
            catalog.hours,
            wave_max=wave_max,
            wave_step=wave_step,
            wind_max=wind_max,
            wind_step=wind_step,
        )
        status = analysis.catalog_status(catalog)
        pdf_bytes = pdf_report.build_pdf(payload, status)
        name = pdf_report.filename(status)
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/refresh")
def refresh():
    body = request.get_json(silent=True) or {}
    kwargs = {}
    if "latitude" in body:
        kwargs["latitude"] = float(body["latitude"])
    if "longitude" in body:
        kwargs["longitude"] = float(body["longitude"])
    if "date_start" in body:
        kwargs["date_start"] = str(body["date_start"])
    if "date_end" in body:
        kwargs["date_end"] = str(body["date_end"])
    return jsonify(analysis.start_refresh(**kwargs))


@app.get("/api/refresh/status")
def refresh_poll():
    return jsonify(analysis.refresh_status())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
