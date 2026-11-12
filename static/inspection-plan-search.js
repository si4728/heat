(() => {
  const search = document.getElementById('plan-exchanger-search');
  const select = document.getElementById('plan-exchanger-select');
  const status = document.getElementById('plan-exchanger-search-status');
  if (!search || !select || !status) return;
  const normalize = text => String(text).normalize('NFKC').toLocaleLowerCase().replace(/[-‐‑–—]/g, '').replace(/\s+/g, ' ').trim();
  const options = Array.from(select.options).filter(option => option.value).map(option => ({value:option.value, text:option.textContent, key:normalize(option.textContent)}));
  function filter() {
    const previous = select.value;
    const words = normalize(search.value).split(' ').filter(Boolean);
    const matches = options.filter(option => words.every(word => option.key.includes(word)));
    select.replaceChildren(new Option(matches.length ? '선택' : '검색 결과 없음', ''));
    for (const item of matches) select.add(new Option(item.text, item.value));
    select.value = matches.some(item => item.value === previous) ? previous : '';
    status.textContent = `검색 결과 ${matches.length.toLocaleString()}대 / 전체 ${options.length.toLocaleString()}대`;
  }
  search.addEventListener('input', filter);
  filter();
})();
