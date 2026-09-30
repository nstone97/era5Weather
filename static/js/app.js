const MONTHS = ["All", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const state = {
  selected: "All",
  payload: null,
};

function qs(name) {
  return document.querySelector(name);
}

function formParams() {
  const data = new FormData(qs("#controls"));
  const params = new URLSearchParams();
  for (const [key, value] of data.entries()) params.set(key, value);
  return params;
}

function cellColor(pct) {
  if (pct == null || Number.isNaN(pct)) return { bg: "#12283a", fg: "#e8eef4" };
  const t = Math.max(0, Math.min(1, pct / 100));
  const stops = [
    [12, 40, 58],
    [30, 77, 123],
    [224, 164, 90],
    [213, 107, 78],
  ];
  const pos = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  const f = pos - i;
  const mix = stops[i].map((c, idx) => Math.round(c + (stops[i + 1][idx] - c) * f));
  const bg = `rgb(${mix.join(",")})`;
  const luminance = (0.299 * mix[0] + 0.587 * mix[1] + 0.114 * mix[2]) / 255;
  return { bg, fg: luminance > 0.62 ? "#07131d" : "#f4f8fb" };
}

function formatPct(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(2)}%`;
}

function renderStats(status) {
  const items = [
    ["Hours", status.hours.toLocaleString()],
    ["Period", `${status.start.slice(0, 10)} → ${status.end.slice(0, 10)}`],
    ["Mean Hs", `${status.swh_mean_ft} ft`],
    ["Median Hs", `${status.swh_median_ft} ft`],
    ["99th Hs", `${status.swh_p99_ft} ft`],
    ["Mean wind", `${status.s10_mean_kt} kt`],
    ["99th wind", `${status.s10_p99_kt} kt`],
  ];
  qs("#stats").innerHTML = items.map(
    ([label, value]) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`
  ).join("");
  qs("#location-line").textContent =
    `Requested ${status.request_latitude.toFixed(3)}°N, ${Math.abs(status.request_longitude).toFixed(3)}°W · ` +
    `wave grid ${status.wave_latitude.toFixed(2)}°N, ${Math.abs(status.wave_longitude).toFixed(2)}°W · ` +
    `wind grid ${status.surface_latitude.toFixed(2)}°N, ${Math.abs(status.surface_longitude).toFixed(2)}°W`;
}

function monthNav() {
  qs("#months").innerHTML = MONTHS.map((name) => {
    const pressed = name === state.selected ? "true" : "false";
    return `<button type="button" data-month="${name}" aria-pressed="${pressed}">${name}</button>`;
  }).join("");
}

function explain(month, wave, wind, pct) {
  qs("#readout").textContent =
    `${formatPct(pct)} of ${month} hours have waves above ${wave} ft or sustained wind above ${wind} kt.`;
}

function tableFor(month) {
  const { wave_thresholds: waves, wind_thresholds: winds, months } = state.payload;
  const grid = months[month];
  const head = ["Hs (ft)", ...winds.map((w) => `${w} kt`)];
  const header = `<tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr>`;
  const body = waves.map((wave, r) => {
    const cells = winds.map((wind, c) => {
      const pct = grid[r][c];
      const { bg, fg } = cellColor(pct);
      return `<td style="background:${bg};color:${fg}">
        <button type="button" data-month="${month}" data-wave="${wave}" data-wind="${wind}" data-pct="${pct}">
          ${formatPct(pct)}
        </button>
      </td>`;
    }).join("");
    return `<tr><th>${wave}</th>${cells}</tr>`;
  }).join("");
  return `<article class="month-card">
    <h3>${month}</h3>
    <table><thead>${header}</thead><tbody>${body}</tbody></table>
  </article>`;
}

function renderTables() {
  const root = qs("#tables");
  if (!state.payload) {
    root.innerHTML = "<p class='error'>No data loaded.</p>";
    return;
  }
  const names = state.selected === "All" ? MONTHS.slice(1) : [state.selected];
  root.className = state.selected === "All" ? "tables grid" : "tables single";
  root.innerHTML = names.map(tableFor).join("");
}

async function loadExceedance() {
  const params = formParams();
  qs("#csv-link").href = `/api/exceedance.csv?${params.toString()}`;
  qs("#tables").innerHTML = "<p>Computing exceedance…</p>";
  const response = await fetch(`/api/exceedance?${params.toString()}`);
  const data = await response.json();
  if (!response.ok) {
    qs("#tables").innerHTML = `<p class="error">${data.error || "Failed to load."}</p>`;
    return;
  }
  state.payload = data;
  renderStats(data.status);
  renderTables();
}

function wire() {
  monthNav();
  qs("#months").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-month]");
    if (!button) return;
    state.selected = button.dataset.month;
    monthNav();
    renderTables();
  });

  qs("#tables").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-pct]");
    if (!button) return;
    explain(button.dataset.month, button.dataset.wave, button.dataset.wind, Number(button.dataset.pct));
  });

  qs("#controls").addEventListener("submit", (event) => {
    event.preventDefault();
    loadExceedance();
  });

  qs("#refresh-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target).entries());
    qs("#refresh-status").textContent = "Starting retrieve…";
    const response = await fetch("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    qs("#refresh-status").textContent = result.message || result.status;
    pollRefresh();
  });
}

async function pollRefresh() {
  const statusEl = qs("#refresh-status");
  const tick = async () => {
    const response = await fetch("/api/refresh/status");
    const result = await response.json();
    statusEl.textContent = `${result.status}: ${result.message || ""}`;
    if (result.status === "running") {
      setTimeout(tick, 2000);
    } else if (result.status === "ready") {
      loadExceedance();
    }
  };
  tick();
}

wire();
loadExceedance();
