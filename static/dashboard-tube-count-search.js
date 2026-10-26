(() => {
  const input = document.getElementById('missing-tube-count-search');
  const table = document.getElementById('missing-tube-count-table');
  const output = document.getElementById('missing-tube-count-visible');
  if (!input || !table || !output) return;
  const rows = [...table.querySelectorAll('tbody tr')].filter(row => row.cells.length === 6);
  const filter = () => {
    const query = input.value.trim().toLocaleLowerCase();
    let visible = 0;
    rows.forEach(row => {
      row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
      if (!row.hidden) visible++;
    });
    output.textContent = `표시 ${visible.toLocaleString('ko-KR')} / 전체 ${rows.length.toLocaleString('ko-KR')}대`;
  };
  input.addEventListener('input', filter);
  filter();
})();
