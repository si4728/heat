(() => {
  const host = document.getElementById("simulation-comparison-chart");
  const source = document.getElementById("simulation-comparison-data");
  if (!host || !source) return;
  const data = JSON.parse(source.textContent);
  const ns = "http://www.w3.org/2000/svg";
  const create = (name, attrs = {}) => {
    const node = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };
  const scenarios = [
    { key: "baseline", label: "현재 기준", color: "#38bdf8", dash: "" },
    { key: "simulation", label: "Simulation", color: "#f97316", dash: "8 5" },
  ].filter(item => data[item.key]);

  function draw() {
    host.replaceChildren();
    const width = Math.max(host.clientWidth, 760), height = 380;
    const margin = { top: 28, right: 28, bottom: 52, left: 58 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const years = scenarios.flatMap(item => data[item.key].series.map(row => row.year));
    if (!years.length) return;
    const minYear = Math.min(...years), maxYear = Math.max(...years);
    const values = scenarios.flatMap(item => data[item.key].series.map(row => row.cumulative_plugging_count));
    const limits = scenarios.map(item => data[item.key].limit || 0);
    const yMax = Math.max(10, data.total || 0, ...values, ...limits);
    const x = year => margin.left + (year - minYear) / Math.max(maxYear - minYear, 1) * plotWidth;
    const y = value => margin.top + plotHeight - value / yMax * plotHeight;
    const svg = create("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height });

    for (let tick = 0; tick <= 5; tick += 1) {
      const value = Math.round(yMax * tick / 5), yy = y(value);
      svg.appendChild(create("line", { x1: margin.left, y1: yy, x2: width - margin.right, y2: yy, class: "simulation-grid-line" }));
      const label = create("text", { x: margin.left - 10, y: yy + 4, class: "simulation-axis-label", "text-anchor": "end" });
      label.textContent = value;
      svg.appendChild(label);
    }

    const yearStep = Math.max(1, Math.ceil((maxYear - minYear + 1) / 8));
    for (let year = minYear; year <= maxYear; year += yearStep) {
      const label = create("text", { x: x(year), y: height - 20, class: "simulation-axis-label", "text-anchor": "middle" });
      label.textContent = year;
      svg.appendChild(label);
    }

    scenarios.forEach(item => {
      const scenario = data[item.key];
      const points = scenario.series.map(row => `${x(row.year)},${y(row.cumulative_plugging_count)}`).join(" ");
      svg.appendChild(create("polyline", { points, fill: "none", stroke: item.color, "stroke-width": 3, "stroke-dasharray": item.dash }));
      svg.appendChild(create("line", { x1: margin.left, y1: y(scenario.limit), x2: width - margin.right, y2: y(scenario.limit), stroke: item.color, "stroke-width": 1.5, "stroke-dasharray": "3 5", opacity: .8 }));
      scenario.series.forEach(row => {
        const point = create("circle", { cx: x(row.year), cy: y(row.cumulative_plugging_count), r: row.life_reached ? 5 : 2.5, fill: item.color });
        const title = create("title");
        title.textContent = `${item.label} ${row.year}: 누적 ${row.cumulative_plugging_count}개`;
        point.appendChild(title);
        svg.appendChild(point);
      });
    });
    host.appendChild(svg);
  }
  new ResizeObserver(draw).observe(host);
  draw();
})();
