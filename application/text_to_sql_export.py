"""Bounded, owner-only exports of completed query results (never client rows)."""
from collections import OrderedDict
from copy import deepcopy
from io import BytesIO
from threading import Lock
from time import monotonic
from uuid import uuid4

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from ..llm_integration.text_to_sql import QueryRejected


class ExportStore:
    def __init__(self):
        self.entries=OrderedDict()
        self.lock=Lock()

    def save(self, owner, signed, result):
        entry=dict(owner=owner, created=monotonic(), signed=deepcopy(signed),
                   result=deepcopy({k:v for k,v in result.items() if k not in ('summary_token','_commentary_facts')}))
        with self.lock:
            self._expire()
            key=uuid4().hex
            self.entries[key]=entry
            while len(self.entries)>32:self.entries.popitem(last=False)
        return key

    def _expire(self):
        for key in list(self.entries):
            if monotonic()-self.entries[key]['created']>900:del self.entries[key]

    def get(self, key, owner):
        with self.lock:
            self._expire()
            entry=self.entries.get(key) if isinstance(key,str) else None
            if not entry or entry['owner']!=owner:
                raise QueryRejected('내보낼 결과가 없거나 만료되었습니다. 다시 조회하세요.')
            return deepcopy(entry)


LABELS={'team_code':'생산팀','unit_code':'공정','exchanger_code':'설비 코드',
        'equipment_code':'설비 코드','equipment_tag':'설비 Tag','equipment_name':'설비명',
        'latest_inspection_date':'최근 검사일','maximum_loss':'최대 감육률 (%)',
        'remaining_display':'예상 잔여수명','remaining_life_years':'예상 잔여수명 (년)',
        'recommendation_date':'차기 검사 권고일','life_source':'산정 근거',
        'matching_tube_count':'조건 해당 튜브 수','measured_estimated_loss':'실측 / 추정 최대 감육률 (%)',
        'first_display':'최초 도달','uncalculable_reason':'산정 불가 사유','tube_material':'현재 Tube 재질',
        'side_code':'측','fluid_name':'유체명','exchanger_count':'열교환기 수','equipment_list':'설비 목록'}


def cell_value(value):
    if value is None or isinstance(value,(int,float,bool)):return value
    return ILLEGAL_CHARACTERS_RE.sub('',str(value))[:32767]


def workbook(entry):
    result,signed=entry['result'],entry['signed']
    book=Workbook()
    sheet=book.active;sheet.title='조회 결과'
    columns=[c for c in result.get('columns',[]) if not c.startswith('_')]
    metadata=[('질문',signed.get('question','')),('조회 시각',result.get('generated_at','')),
              ('해석 조건',signed.get('interpretation') or result.get('filter_description') or signed.get('settings',{}).get('description') or signed.get('question','')),
              ('조회 범위',' · '.join(f"{s.get('equipment',{}).get('unit_code','')} {s.get('equipment',{}).get('equipment_tag') or s.get('equipment',{}).get('heat_exchanger_id','')}" for s in signed.get('export_scopes',[]))),
              ('내보내기 범위',f"화면 결과 {len(result['rows'])}행 / 조건 부합 {result.get('matched_count',result.get('result_count',0))}행"),
              ('표시 제한', '표시 상한 적용: 전체 결과가 아닙니다.' if result.get('limit_reached') else '화면 표시 결과 전체'),
              ('계산 기준일',result.get('calculation_date') or ' · '.join(sorted({str(r['calculation_date']) for r in result['rows'] if r.get('calculation_date')})) or '결과별 기준 참조')]
    for row in metadata:sheet.append([cell_value(v) for v in row])
    for index,(_,value) in enumerate(metadata,1):
        sheet.row_dimensions[index].height=min(100, max(30, 15*(len(str(value))//24+1)))
    sheet.append([])
    sheet.append([LABELS.get(c,c) for c in columns]);header=sheet.max_row
    for row in result['rows']:sheet.append([cell_value(row.get(c)) for c in columns])
    # Force every text cell to a string, including values beginning with =,+,-,@.
    for row in sheet:
        for cell in row:
            if isinstance(cell.value,str):cell.data_type='s'
            cell.alignment=Alignment(vertical='top',wrap_text=True)
    for cell in sheet[header]:
        cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='253746')
    for index in range(1,max(len(columns),2)+1):sheet.column_dimensions[get_column_letter(index)].width=25 if index>1 else 22
    sheet.freeze_panes=f'A{header+1}'
    if columns:sheet.auto_filter.ref=f'A{header}:{get_column_letter(len(columns))}{sheet.max_row}'
    output=BytesIO();book.save(output);output.seek(0)
    return output
