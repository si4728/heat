(() => {
  const helpModal = document.getElementById("plugging-help-modal");
  if (helpModal) {
    const closeHelp = () => {
      helpModal.hidden = true;
      document.body.style.overflow = "";
    };
    document.querySelectorAll("[data-plugging-help]").forEach((button) => {
      button.addEventListener("click", () => {
        helpModal.hidden = false;
        document.body.style.overflow = "hidden";
        helpModal.querySelector("[data-plugging-help-close]")?.focus();
      });
    });
    helpModal.querySelectorAll("[data-plugging-help-close]").forEach((button) => {
      button.addEventListener("click", closeHelp);
    });
    helpModal.addEventListener("click", (event) => {
      if (event.target === helpModal) closeHelp();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !helpModal.hidden) closeHelp();
    });
  }

  const host = document.getElementById("life-bar-chart");
  const source = document.getElementById("life-chart-data");
  if (!host || !source) return;
  const data = JSON.parse(source.textContent);
  const ns = "http://www.w3.org/2000/svg";
  const create = (name, attrs = {}) => {
    const node = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };

  function draw() {
    host.replaceChildren();
    const width = Math.max(host.clientWidth, 720), height = 330;
    const margin = { top: 22, right: 18, bottom: 48, left: 52 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maximum = Math.max(data.total || 0, data.allowable || 0,
      ...data.series.map(item => item.cumulative_plugging_count), 10);
    const yMax = Math.ceil(maximum / 10) * 10;
    const xStep = plotWidth / data.series.length;
    const barWidth = Math.max(8, xStep * .56);
    const y = value => margin.top + plotHeight - value / yMax * plotHeight;
    const svg = create("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height });

    for (let tick = 0; tick <= 5; tick += 1) {
      const value = Math.round(yMax * tick / 5), yy = y(value);
      svg.appendChild(create("line", { x1: margin.left, y1: yy, x2: width - margin.right, y2: yy, class: "life-grid-line" }));
      const label = create("text", { x: margin.left - 10, y: yy + 4, class: "life-axis-label", "text-anchor": "end" });
      label.textContent = value;
      svg.appendChild(label);
    }

    data.series.forEach((item, index) => {
      const x = margin.left + index * xStep + (xStep - barWidth) / 2;
      const top = y(item.cumulative_plugging_count);
      const bar = create("rect", { x, y: top, width: barWidth,
        height: Math.max(margin.top + plotHeight - top, 0), rx: 1,
        class: `life-bar${item.life_reached ? " reached" : ""}` });
      const title = create("title");
      title.textContent = `${item.year}년 · 누적 Plugging ${item.cumulative_plugging_count}개`;
      bar.appendChild(title);
      svg.appendChild(bar);
      const label = create("text", { x: x + barWidth / 2, y: height - 18,
        class: "life-axis-label", "text-anchor": "middle" });
      label.textContent = item.year;
      svg.appendChild(label);
    });

    const limitY = y(data.allowable);
    svg.appendChild(create("line", { x1: margin.left, y1: limitY,
      x2: width - margin.right, y2: limitY, class: "life-limit-line" }));
    host.appendChild(svg);
  }

  new ResizeObserver(draw).observe(host);
  draw();
})();
