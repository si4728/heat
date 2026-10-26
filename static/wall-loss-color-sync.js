(() => {
  const storageKey = 'iris2.wall-loss-colors';
  const settings = document.getElementById('wall-loss-saved-colors');
  if (settings) {
    // Publish only server-confirmed colors after saving/resetting, never picker edits.
    try {
      const saved = JSON.stringify(JSON.parse(settings.textContent));
      if (localStorage.getItem(storageKey) !== saved) localStorage.setItem(storageKey, saved);
    } catch { /* Storage may be disabled; normal page reloads still apply saved colors. */ }
  }
  const precision = document.getElementById('precision-map-data');
  if (!precision && !document.getElementById('tube-map-app')) return;
  const renderedColors = precision ? JSON.parse(precision.textContent).colors : null;
  window.addEventListener('storage', event => {
    if (event.key !== storageKey || !event.newValue || event.newValue === event.oldValue) return;
    let colors;
    try { colors = JSON.parse(event.newValue); } catch { return; }
    const keys = ['NORMAL', 'WARNING', 'CRITICAL', 'NOT_INSPECTED', 'PLUGGED'];
    if (!keys.every(key => /^#[0-9a-f]{6}$/i.test(colors?.[key] || ''))) return;
    if (renderedColors && keys.every(key => colors[key].toLowerCase() === renderedColors[key]?.toLowerCase())) return;
    window.location.reload();
  });
})();
