"""Request-wide audit hooks. Never serialize a query string, body, cookie or token."""
from datetime import datetime, timezone
import time
import uuid

from flask import g, request, session

from ..application.access_audit import append_events, clean_text


def auth_event(event_type, result, reason, user=None):
    g.audit_auth_event = (event_type,result,reason)
    if user:
        g.audit_user_id = user['user_id']
        g.audit_username = user.get('username','')
    g.audit_session_id = session.get('audit_session_id') or g.get('audit_session_id')


def register_access_audit(app, endpoint_permissions):
    app.config.setdefault('ACCESS_AUDIT_ENABLED',not app.testing)
    app.extensions['access_audit'] = dict(failures=0,last_failure_at=None)
    excluded = {'static','api_health','hanwha_solution_logo','hanwha_solution_logo_legacy'}
    system_screens = {'users_admin':'USERS','access_logs':'ACCESS_LOGS',
        'access_logs_export':'ACCESS_LOGS','database_monitor':'DATABASE_MONITOR',
        'backup_manager':'BACKUPS','data_entry_status':'DATA_ENTRY_STATUS','imports':'IMPORTS',
        'login':'LOGIN','logout':'LOGIN','setup_admin':'USERS','user_preferences':'PREFERENCES'}

    @app.before_request
    def begin_access_audit():
        g.audit_started = time.monotonic()
        g.audit_created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        g.audit_request_id = uuid.uuid4().hex
        g.audit_user_id = session.get('user_id')
        g.audit_username = session.get('audit_username','')
        g.audit_session_id = session.get('audit_session_id')
        g.audit_reason = ''

    @app.after_request
    def finish_access_audit(response):
        if request.endpoint in ('access_logs','access_logs_export'):
            response.headers['Cache-Control'] = 'no-store'
        if not app.config['ACCESS_AUDIT_ENABLED'] or request.endpoint in excluded or request.path == '/favicon.ico':
            return response
        profile = g.get('current_user') or {}
        user_id = profile.get('user_id') or g.get('audit_user_id')
        username = profile.get('username') or g.get('audit_username','')
        reason = g.get('audit_reason','')
        status = response.status_code
        if reason or status in (401,403):
            result = 'DENIED'
            reason = reason or 'PERMISSION_DENIED'
        elif status >= 400:
            result,reason = 'ERROR','HTTP_ERROR'
        elif status >= 300:
            result = 'REDIRECT'
        else:
            result = 'ALLOWED'
        if not reason and not user_id:
            reason = 'AUTH_DISABLED' if app.config.get('AUTH_DISABLED') else 'ANONYMOUS'
        common = dict(created_at=g.audit_created_at,request_id=g.audit_request_id,
            audit_session_id=g.get('audit_session_id'),user_id=user_id,
            username=clean_text(username,100),method=clean_text(request.method,12),
            path=clean_text(request.path,1024),endpoint=clean_text(request.endpoint,120),
            screen_key=clean_text(system_screens.get(request.endpoint,endpoint_permissions.get(request.endpoint,'')),60),
            status_code=status,client_ip=clean_text(request.remote_addr,45),
            user_agent=clean_text(request.user_agent.string,512),
            duration_ms=min(2147483647,max(0,round((time.monotonic()-g.audit_started)*1000))))
        events = [dict(common,event_type='ACCESS',result=result,reason=reason)]
        if g.get('audit_auth_event'):
            event_type,event_result,event_reason = g.audit_auth_event
            events.append(dict(common,event_type=event_type,result=event_result,reason=event_reason))
        try:
            append_events(events)
            response.headers['X-Audit-Recorded'] = '1'
        except Exception as error:
            state = app.extensions['access_audit']
            state['failures'] += 1
            state['last_failure_at'] = datetime.now(timezone.utc).isoformat()
            # Do not print SQL parameters, user input, credentials, or exception messages.
            app.logger.error('Access audit write failed request_id=%s error_type=%s',g.audit_request_id,type(error).__name__)
            response.headers['X-Audit-Recorded'] = '0'
        return response
