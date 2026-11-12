(() => {
  for (const details of document.querySelectorAll('.recommendation-register')) {
    const form = details.querySelector('form');
    const select = form.querySelector('[name=tube_ids]');
    const state = form.querySelector('[data-plan-load-state]');
    const submit = form.querySelector('[type=submit]');
    let loaded = false;
    let loading = false;
    const refresh = () => {
      const count = [...select.selectedOptions].length;
      state.textContent = select.options.length ? `선택 ${count}본 / 사용 중 ${select.options.length}본` : '현재 사용 중인 등록 Tube가 없습니다. 튜브 등록 상태를 확인하세요.';
      submit.disabled = count === 0;
    };
    details.addEventListener('toggle', async () => {
      if (!details.open || loaded || loading) return;
      loading = true;
      try {
        const response = await fetch(details.dataset.tubesUrl, {headers: {'Accept': 'application/json'}});
        if (!response.ok || response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('조회 실패');
        const data = await response.json();
        for (const tube of data.tubes) {
          const option = document.createElement('option');
          option.value = tube.tube_id;
          option.textContent = `Tube ${tube.tube_no}`;
          select.appendChild(option);
        }
        loaded = true;
        refresh();
      } catch {
        state.textContent = '대상 Tube를 불러오지 못했습니다. 로그인과 조회 권한을 확인한 뒤 다시 열어 주세요.';
      } finally {
        loading = false;
      }
    });
    select.addEventListener('change', refresh);
    form.querySelector('[data-plan-select-all]').addEventListener('click', () => {
      for (const option of select.options) option.selected = true;
      refresh();
    });
    form.addEventListener('submit', () => {submit.disabled = true;});
  }
})();
