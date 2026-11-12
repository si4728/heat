"""Render the real application shell without DB access; no business data is fabricated."""
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.taste-skill'
env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=True)
env.globals.update(
    url_for=lambda endpoint, **kw: '/static/' + kw['filename'] if endpoint == 'static' else '#'+endpoint,
    can_screen=lambda *args: True,
    get_flashed_messages=lambda **kw: [],
)
content = '''<p class="coverage-basis">화면 검토용 미리보기 · MariaDB 미연결 · 실제 집계값은 표시하지 않습니다.</p>
<article class="panel"><div class="panel-head"><div><p class="eyebrow">VCM1 · VCM2</p><h2>열교환기 잔여수명 현황</h2></div><a href="#exchangers">설비 목록 보기 →</a></div>
<div class="table-wrap"><table><thead><tr><th>공정</th><th>5년 미만</th><th>5–10년</th><th>10년 이상</th><th>산정 불가</th><th>합계</th></tr></thead><tbody><tr><td>VCM1</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr><tr><td>VCM2</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr></tbody></table></div></article>
<div class="metrics" style="margin-top:18px">'''+''.join('<article><span>'+label+'</span><strong>—</strong><small>데이터 미연결</small></article>' for label in ['열교환기','검사 이력','전체 튜브','튜브 결과','검사 계획'])+'''</div>
<div class="grid two"><article class="panel"><div class="panel-head"><h2>최근 검사</h2><a href="#inspections">검사 이력 →</a></div><div class="empty">MariaDB 연결 후 검사 이력을 확인할 수 있습니다.</div></article><article class="panel"><div class="panel-head"><h2>예정 검사</h2><a href="#inspection_plans">계획 관리 →</a></div><div class="empty">MariaDB 연결 후 검사계획을 확인할 수 있습니다.</div></article></div>'''
for stage in ['before', 'after']:
    source = (OUT / 'rollback-20261102/base.html' if stage == 'before' else ROOT / 'templates/base.html').read_text(encoding='utf-8')
    for theme in ['ORANGE', 'DEFAULT']:
        template = env.from_string(source.replace('{% block content %}{% endblock %}', content))
        page = template.render(active_theme=SimpleNamespace(preset_key=theme, background_color='#f4f4f4' if theme=='ORANGE' else '#060e15', label_color='#626b65' if theme=='ORANGE' else '#aeb6b2'), request=SimpleNamespace(endpoint='dashboard'), current_user=None, database_path='MariaDB · IRIS2', csrf_token='')
        (OUT / f'{stage}-{theme.lower()}.html').write_text(page, encoding='utf-8')
print('Rendered before/after shells for light and dark themes; no database access.')
