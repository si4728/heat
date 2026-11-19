"""Append-only authentication and HTTP access audit, with bounded read queries."""
from __future__ import annotations

import csv
import io
import ipaddress
import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import BigInteger, Column, Index, Integer, String, func, select
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import declarative_base

from ..database import get_engine

Base = declarative_base()
KST = timezone(timedelta(hours=9))
EVENTS = {'ACCESS': '화면·API 접근', 'LOGIN_SUCCESS': '로그인 성공',
          'LOGIN_FAILURE': '로그인 실패', 'LOGOUT': '로그아웃',
          'SESSION_EXPIRED': '세션 만료', 'SESSION_INVALID': '세션 무효',
          'INITIAL_ADMIN': '초기 관리자 등록'}
RESULTS = {'ALLOWED': '허용', 'DENIED': '거부', 'ERROR': '오류',
           'REDIRECT': '이동', 'SUCCESS': '성공', 'FAILURE': '실패'}
REASONS = {'AUTH_REQUIRED': '로그인 필요', 'INVALID_CREDENTIALS': '인증 실패',
           'CSRF_REJECTED': '요청 검증 실패', 'PERMISSION_DENIED': '권한 없음',
           'SESSION_EXPIRED': '미사용 시간 초과', 'SESSION_INVALID': '계정·세션 무효',
           'AUTHENTICATED': '인증 완료', 'USER_LOGOUT': '사용자 로그아웃',
           'INITIAL_ADMIN': '초기 관리자 등록', 'HTTP_ERROR': 'HTTP 오류',
           'ANONYMOUS': '비로그인 접근', 'AUTH_DISABLED': '인증 비활성 설정',
           '': '−'}


class AccessAuditEvent(Base):
    __tablename__ = 'access_audit_event'
    __table_args__ = (
        Index('ix_access_audit_created', 'created_at', 'audit_event_id'),
        Index('ix_access_audit_user_time', 'user_id', 'created_at'),
        Index('ix_access_audit_session_time', 'audit_session_id', 'created_at'),
        Index('ix_access_audit_event_time', 'event_type', 'created_at'),
        Index('ix_access_audit_result_time', 'result', 'created_at'),
        Index('ix_access_audit_request', 'request_id'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'},
    )
    audit_event_id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(DATETIME(fsp=6), nullable=False)
    request_id = Column(String(32), nullable=False)
    audit_session_id = Column(String(32))
    # Intentionally no FK: historical evidence survives deletion/deactivation of an account.
    user_id = Column(Integer)
    username = Column(String(100), nullable=False, default='')
    event_type = Column(String(24), nullable=False)
    result = Column(String(16), nullable=False)
    reason = Column(String(40), nullable=False, default='')
    method = Column(String(12), nullable=False)
    path = Column(String(1024), nullable=False)
    endpoint = Column(String(120), nullable=False, default='')
    screen_key = Column(String(60), nullable=False, default='')
    status_code = Column(Integer, nullable=False)
    client_ip = Column(String(45), nullable=False, default='')
    user_agent = Column(String(512), nullable=False, default='')
    duration_ms = Column(Integer, nullable=False)


def clean_text(value, limit):
    return ''.join(c for c in str(value or '') if c >= ' ' and c != '\x7f')[:limit]


def append_events(events):
    """One separate transaction, so failed business requests still leave evidence."""
    if events:
        with get_engine().begin() as connection:
            connection.execute(AccessAuditEvent.__table__.insert(), events)


def parse_filters(values):
    today = datetime.now(KST).date()
    filters = {key: clean_text(values.get(key, ''), size).strip() for key, size in
               [('start',10),('end',10),('user',100),('event',24),('result',16),
                ('ip',45),('path',200),('screen',60),('session',32)]}
    filters['start'] = filters['start'] or (today - timedelta(days=6)).isoformat()
    filters['end'] = filters['end'] or today.isoformat()
    try:
        start, end = date.fromisoformat(filters['start']), date.fromisoformat(filters['end'])
        if start > end:
            raise ValueError()
        start_utc = datetime.combine(start,time.min,KST).astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = datetime.combine(end+timedelta(days=1),time.min,KST).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise ValueError('조회 시작일과 종료일을 확인해 주세요.') from None
    if filters['event'] and filters['event'] not in EVENTS:
        raise ValueError('올바른 이벤트를 선택해 주세요.')
    if filters['result'] and filters['result'] not in RESULTS:
        raise ValueError('올바른 결과를 선택해 주세요.')
    if filters['session'] and not re.fullmatch('[0-9a-f]{32}',filters['session']):
        raise ValueError('올바른 접속 식별자를 입력해 주세요.')
    if filters['ip']:
        try:
            filters['ip'] = str(ipaddress.ip_address(filters['ip']))
        except ValueError:
            raise ValueError('올바른 접속 IP를 입력해 주세요.') from None
    table = AccessAuditEvent
    conditions = [table.created_at >= start_utc,table.created_at < end_utc]
    for key, column in [('event',table.event_type),('result',table.result),
                        ('ip',table.client_ip),('screen',table.screen_key),('session',table.audit_session_id)]:
        if filters[key]:
            conditions.append(column == filters[key])
    for key, column in [('user',table.username),('path',table.path)]:
        if filters[key]:
            conditions.append(column.contains(filters[key],autoescape=True))
    return filters, conditions


def audit_rows(values, *, page=1, export=False):
    filters, conditions = parse_filters(values)
    page_size = 50
    if page < 1 or page > 1000000:
        raise ValueError('올바른 페이지를 선택해 주세요.')
    table = AccessAuditEvent.__table__
    with get_engine().connect() as connection:
        # A single repeatable-read connection keeps count and displayed rows consistent.
        total = connection.scalar(select(func.count()).select_from(table).where(*conditions))
        statement = select(table).where(*conditions).order_by(table.c.created_at.desc(),table.c.audit_event_id.desc())
        statement = statement.limit(10001) if export else statement.limit(page_size).offset((page-1)*page_size)
        rows = [dict(row) for row in connection.execute(statement).mappings()]
    truncated = export and len(rows) > 10000
    rows = rows[:10000] if export else rows
    for row in rows:
        row['occurred_at'] = row['created_at'].replace(tzinfo=timezone.utc).astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')
    return dict(filters=filters,rows=rows,total=total,page=page,page_size=page_size,
                pages=max(1,(total+page_size-1)//page_size),truncated=truncated,
                event_labels=EVENTS,result_labels=RESULTS,reason_labels=REASONS)


def csv_cell(value):
    text = str(value if value is not None else '')
    return "'"+text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t','\r','\n')) else text


def export_csv(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['이력 ID','일시(KST)','사용자 ID','사용자','이벤트','결과','사유',
                     '화면','HTTP','경로','상태','IP','브라우저','처리시간(ms)','접속 식별자','요청 식별자'])
    for row in rows:
        values = [row['audit_event_id'],row['occurred_at'],row['user_id'],row['username'],
                  EVENTS.get(row['event_type'],row['event_type']),RESULTS.get(row['result'],row['result']),
                  REASONS.get(row['reason'],row['reason']),row['screen_key'],row['method'],row['path'],
                  row['status_code'],row['client_ip'],row['user_agent'],row['duration_ms'],row['audit_session_id'],row['request_id']]
        writer.writerow([csv_cell(value) for value in values])
    return '\ufeff'+stream.getvalue()
