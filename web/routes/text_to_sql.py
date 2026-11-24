from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime
from http import HTTPStatus
from uuid import uuid4
from iris2 import dbapi

from flask import abort, copy_current_request_context, g, jsonify, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException

from iris2 import services
from iris2.application import text_to_sql_service as analysis
from iris2.application import inspection_frequency as frequency
from iris2.application import query_period
from iris2.application import text_to_sql_help
from iris2.application import text_to_sql_reports
from iris2.application import text_to_sql_fluids as fluids
from iris2.application import text_to_sql_equipment as equipment_query
from iris2.application import text_to_sql_commentary as commentary
from iris2.llm_integration.question_language import normalize
from iris2.application import text_to_sql_usage_log as usage_log
from iris2.application.model_queue import ModelQueue, QueueFull
from iris2.hx_configuration import APP_DIR
from iris2.llm_integration.text_to_sql import (
    QueryRejected, execute_proposal, validate_proposal, validate_question_contract,
)


def register_routes(app):
    model_queue = ModelQueue()
    app.extensions['text_to_sql_model_queue'] = model_queue

    def enqueue_model(handler, profile):
        owner = profile['user_id']
        submitted_record = deepcopy(usage_record())
        submitted_at = g.text_sql_started

        @copy_current_request_context
        def run():
            g.text_sql_usage = submitted_record
            g.text_sql_started = submitted_at
            g.text_sql_model_worker = True
            try:
                # A waiting user's account/permissions may have changed since submission.
                g.current_user = services.user_access_profile(owner)
                if not g.current_user or not g.current_user.get('is_active'):
                    response = app.make_response((jsonify(
                        error='계정이 비활성화되었거나 조회 권한이 변경되었습니다.'), 403))
                else:
                    response = app.make_response(handler())
            except HTTPException as exc:
                response = app.make_response((jsonify(error='조회 권한을 확인하세요.'), exc.code))
            except Exception as exc:
                response = app.make_response(fail(exc))
            response = protect_text_to_sql_response(response)
            return (response.get_json(silent=True) or dict(error='모델 요청 처리에 실패했습니다.'),
                    response.status_code, response.headers.get('X-Text-to-SQL-Usage-ID'))

        try:
            key = model_queue.submit(owner, run, kind=request.endpoint)
        except QueueFull:
            return jsonify(error='현재 모델 대기 요청이 3개입니다. 나중에 다시 이용해 주세요.'), 429
        g.text_sql_queue_submission = True  # The worker writes the final usage record.
        if body().get('async_model') is True:
            state = model_queue.status(key, owner)
            state['status_url'] = url_for('text_to_sql_model_job', job_id=key)
            return jsonify(model_job=state), 202
        completed = model_queue.wait(key, owner)
        response = jsonify(completed['result'])
        response.status_code = completed['http_status']
        if completed['usage_id']:
            response.headers['X-Text-to-SQL-Usage-ID'] = completed['usage_id']
        return response

    @app.get('/inspections/text-to-sql/model-jobs/<job_id>')
    def text_to_sql_model_job(job_id):
        profile = authorize()
        state = model_queue.status(job_id, profile['user_id'])
        if state is None:
            return jsonify(error='대기 요청이 없거나 만료되었습니다. 다시 요청하세요.'), 404
        if state['kind'] == 'text_to_sql_summarize' and not all(
                services.user_can(profile, key) for key in ('REMAINING_LIFE', 'EXCHANGERS')):
            abort(403)
        return jsonify(model_job=state)

    def usage_record():
        if not hasattr(g, 'text_sql_usage'):
            profile = g.get('current_user') or {}
            data = request.get_json(silent=True)
            g.text_sql_usage = dict(schema_version=1, usage_id=uuid4().hex,
                event_id=uuid4().hex, event=request.endpoint.rsplit('_', 1)[-1],
                requested_at=datetime.now(usage_log.KST).isoformat(timespec='milliseconds'),
                actor={key: profile.get(key) for key in ('user_id', 'username', 'is_admin')},
                input=usage_log.input_context(data), query_kind='tube_analysis',
                scopes=[], excluded=[], sql=None, parameters=[], result=None)
            g.text_sql_usage['actor']['user_id'] = profile.get('user_id', session.get('user_id'))
            g.text_sql_started = time.monotonic()
        return g.text_sql_usage

    def record_scopes(scopes, excluded=None):
        usage_record()['scopes'] = scopes
        if excluded is not None:
            usage_record()['excluded'] = excluded

    def signed_usage(signed):
        record = usage_record()
        record['usage_id'] = signed.get('usage_id', record['usage_id'])
        record['input'] = signed.get('usage_input', usage_log.input_context(
            dict(question=signed.get('question'), exchanger_id=signed.get('exchanger_id'),
                 inspection_id=signed.get('inspection_id'))))
        record['query_kind'] = signed.get('query_kind', 'tube_analysis')
        usage_log.proposal_context(record, signed.get('proposal'))
        pairs = signed.get('scopes') or ([(signed['exchanger_id'], signed['inspection_id'])]
            if 'exchanger_id' in signed else [])
        record_scopes([dict(equipment=dict(heat_exchanger_id=i),
                            inspection=dict(iris_inspection_id=j)) for i, j in pairs])

    def authorize():
        profile = g.get('current_user')
        # Fail closed even if the rest of the app is in AUTH_DISABLED mode.
        if not profile or not all(services.user_can(profile, key) for key in ('TEXT_TO_SQL', 'INSPECTIONS')):
            abort(403)
        return profile

    def serializer():
        return URLSafeTimedSerializer(app.secret_key, salt='iris2-text-to-sql-v1')

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise QueryRejected('요청 내용을 확인하세요.')
        return data

    def identifier(value, *, optional=False):
        if optional and value in (None, ''):
            return None
        if type(value) is not int or value <= 0:
            raise QueryRejected('설비와 검사 회차를 선택하세요.')
        return value

    def fail(exc):
        if request.endpoint in ('text_to_sql_generate', 'text_to_sql_execute', 'text_to_sql_summarize'):
            usage_record()['error_type'] = type(exc).__name__
        if isinstance(exc, PermissionError):
            return jsonify(error=str(exc)), 403
        if isinstance(exc, QueryRejected):
            return jsonify(error=str(exc)), 400
        app.logger.warning('Text-to-SQL request failed (%s)', type(exc).__name__)
        return jsonify(error='조회 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.'), 503

    @app.get('/inspections/text-to-sql')
    def text_to_sql():
        authorize()
        try:
            equipment = analysis.catalog()
            error = None
        except Exception as exc:
            # Never log exception text: database errors may contain account or host details.
            code = exc.args[0] if exc.args and type(exc.args[0]) is int else None
            app.logger.warning('Text-to-SQL catalog failed type=%s db_code=%s',
                               type(exc).__name__, code)
            if isinstance(exc, ValueError):
                detail = '관리자에게 config/database.conf 및 config/database-text-to-sql.conf의 존재·읽기 권한·설정 형식을 확인해 달라고 요청하세요.'
            elif isinstance(exc, dbapi.DatabaseError) and code in (1044, 1045):
                detail = '관리자에게 Text-to-SQL 전용 DB 계정의 로그인 정보와 DB 접근 권한을 확인해 달라고 요청하세요.'
            elif isinstance(exc, dbapi.DatabaseError) and code in (1142, 1143):
                detail = '관리자에게 Text-to-SQL 전용 DB 계정의 설비·공정 테이블 SELECT 권한을 확인해 달라고 요청하세요.'
            else:
                detail = '관리자에게 MariaDB 연결과 Text-to-SQL 전용 읽기 계정 설정을 확인해 달라고 요청하세요.'
            equipment, error = [], '설비 목록을 불러올 수 없습니다. ' + detail
        response = app.make_response(render_template('text_to_sql.html', equipment=equipment, catalog_error=error))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/inspections/text-to-sql/inspections')
    def text_to_sql_inspections():
        authorize()
        try:
            exchanger_id = request.args.get('exchanger_id', type=int)
            identifier(exchanger_id)
            if exchanger_id not in {r['heat_exchanger_id'] for r in analysis.catalog()}:
                raise PermissionError('PE·VCM1·VCM2 범위의 설비를 선택하세요.')
            return jsonify(inspections=analysis.inspections(exchanger_id))
        except Exception as exc:
            return fail(exc)

    @app.post('/inspections/text-to-sql/generate')
    def text_to_sql_generate():
        record = usage_record()
        profile = authorize()
        try:
            data = body()
            question = data.get('question')
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
                raise QueryRejected('질문은 1~500자로 입력하세요.')
            if text_to_sql_help.matches(question):
                record['query_kind'] = 'help'
                return jsonify(text_to_sql_help.response())
            if (data.get('result_unit') == 'equipment' and not text_to_sql_reports.matches(question)
                    and not fluids.matches(question) and not frequency.matches(question)):
                if not all(services.user_can(profile,key) for key in ('REMAINING_LIFE','EXCHANGERS')):
                    raise PermissionError('열교환기·잔여수명 조회 권한이 필요합니다.')
                settings=equipment_query.options(question)
                selected=fluids.select_equipment(data,question)
                ids=[r['heat_exchanger_id'] for r in selected]
                proposal=equipment_query.proposal(ids)
                record['query_kind']='equipment_analysis'
                record_scopes([dict(equipment=row,inspection=None) for row in selected])
                usage_log.proposal_context(record,proposal)
                token=serializer().dumps(dict(actor=profile['user_id'],query_kind='equipment_analysis',
                    ids=ids,settings=settings,proposal=proposal,question=question,
                    usage_id=record['usage_id'],usage_input=record['input']))
                return jsonify(query_kind='equipment_analysis',proposal=proposal,token=token,
                    equipment_list=selected,settings=settings)
            if fluids.matches(question):
                record['query_kind'] = 'fluid_grouping'
                settings = fluids.options(question)
                selected = fluids.select_equipment(data, question)
                ids = [row['heat_exchanger_id'] for row in selected]
                record_scopes([dict(equipment=row, inspection=None) for row in selected])
                proposal = fluids.proposal(ids, settings)
                usage_log.proposal_context(record, proposal)
                token = serializer().dumps(dict(actor=profile['user_id'], query_kind='fluid_grouping',
                    ids=ids, settings=settings, proposal=proposal, question=question,
                    usage_id=record['usage_id'], usage_input=record['input']))
                return jsonify(query_kind='fluid_grouping', proposal=proposal, token=token,
                               equipment_list=selected, settings=settings)
            if text_to_sql_reports.matches(question):
                record['query_kind'] = 'inspection_reports'
                result = text_to_sql_reports.response(question, data)
                record_scopes(result.pop('scopes'))
                record['result'] = dict(result_count=len(result['reports']), limit_reached=result['limit_reached'])
                return jsonify(result)
            if frequency.matches(question):
                record['query_kind'] = 'inspection_frequency'
                catalog = analysis.catalog()
                ids = data.get('exchanger_ids')
                units = data.get('unit_codes')
                if 'exchanger_id' in data:
                    if ids is not None or units is not None:
                        raise QueryRejected('조회 범위 선택 방식을 하나만 지정하세요.')
                    ids = [identifier(data['exchanger_id'])]
                if units is not None:
                    if ids is not None or not isinstance(units,list) or not units or any(u not in ('PE','VCM1','VCM2') for u in units):
                        raise QueryRejected('PE·VCM1·VCM2 공정 또는 교환기를 선택하세요.')
                    selected = [row for row in catalog if row['unit_code'] in units]
                elif ids is not None:
                    if not isinstance(ids,list) or not ids or any(type(i) is not int or i<=0 for i in ids):
                        raise QueryRejected('교환기를 선택하세요.')
                    if not set(ids)<={row['heat_exchanger_id'] for row in catalog}:
                        raise PermissionError('PE·VCM1·VCM2 범위의 설비를 선택하세요.')
                    selected = [row for row in catalog if row['heat_exchanger_id'] in ids]
                else:
                    selected = catalog
                from iris2.application.text_to_sql_scope import mentioned_units
                named_units = mentioned_units(question)
                selected = [row for row in selected if not named_units or row['unit_code'] in named_units]
                ids = [row['heat_exchanger_id'] for row in selected]
                record_scopes([dict(equipment=row, inspection=None) for row in selected])
                period = frequency.options(question)
                record['period'] = period
                proposal = frequency.proposal(ids,period)
                usage_log.proposal_context(record, proposal)
                token = serializer().dumps(dict(actor=profile['user_id'],query_kind='inspection_frequency',
                    ids=ids,period=period,proposal=proposal, question=question,
                    usage_id=record['usage_id'],usage_input=record['input']))
                return jsonify(proposal=proposal,token=token,query_kind='inspection_frequency',period=period,
                               equipment_list=selected)
            from iris2.application import wall_loss_exchanger_count as exchanger_count
            grouped_count = exchanger_count.matches(question)
            if grouped_count:
                # Validate the intent before resolving scopes or spending model time.
                exchanger_count.proposal(question)
                if not any(key in data for key in ('exchanger_id', 'exchanger_ids', 'unit_codes')):
                    data['unit_codes'] = ['PE', 'VCM1', 'VCM2']
                record['query_kind'] = 'wall_loss_exchanger_count'
            period, model_question = query_period.parse(normalize(question))
            multi = 'exchanger_ids' in data or 'unit_codes' in data
            if period is not None:
                if 'exchanger_id' in data and multi:
                    raise QueryRejected('조회 범위 선택 방식을 하나만 지정하세요.')
                ids = ([identifier(data['exchanger_id'])] if 'exchanger_id' in data else data.get('exchanger_ids'))
                scopes, excluded, _ = analysis.select_period_scopes(period,
                    exchanger_ids=ids, unit_codes=data.get('unit_codes'),
                    inspection_id=data.get('inspection_id'))
                equipment, inspection = scopes[0]['equipment'], scopes[0]['inspection']
                multi = True
                record['period'] = period
            elif multi:
                if 'exchanger_id' in data:
                    raise QueryRejected('조회 범위 선택 방식을 하나만 지정하세요.')
                scopes, excluded, _ = analysis.select_scopes(
                    exchanger_ids=data.get('exchanger_ids'), unit_codes=data.get('unit_codes'),
                    inspection_id=data.get('inspection_id'))
                equipment, inspection = scopes[0]['equipment'], scopes[0]['inspection']
            else:
                equipment, inspection, _ = analysis.select_scope(
                    identifier(data.get('exchanger_id')),
                    identifier(data.get('inspection_id'), optional=True))
                scopes, excluded = [dict(equipment=equipment, inspection=inspection)], []
            from iris2.application.text_to_sql_scope import mentioned_units
            named_units = mentioned_units(question)
            if named_units:
                scopes = [s for s in scopes if s['equipment']['unit_code'] in named_units]
                if not scopes:
                    raise QueryRejected('질문의 공정과 선택 범위가 일치하지 않습니다.')
                equipment, inspection = scopes[0]['equipment'], scopes[0]['inspection']
            record_scopes(scopes, excluded)
            if not grouped_count and not g.get('text_sql_model_worker'):
                return enqueue_model(text_to_sql_generate, profile)
            proposal = (exchanger_count.proposal(model_question.strip()) if grouped_count
                        else analysis.generate_in_worker(model_question.strip()))
            usage_log.proposal_context(record, proposal)
            sql, parameters = validate_proposal(proposal)
            validate_question_contract(question, proposal)
            proposal = dict(sql=sql, parameters=parameters)
            usage_log.proposal_context(record, proposal)
            group_units = (data.get('unit_codes') or sorted({s['equipment']['unit_code'] for s in scopes})) if grouped_count else None
            if group_units and named_units:
                group_units = [unit for unit in group_units if unit in named_units]
            token = serializer().dumps(dict(
                actor=profile['user_id'], question=question.strip(), proposal=proposal, period=period,
                query_kind='wall_loss_exchanger_count' if grouped_count else 'tube_analysis', group_units=group_units,
                usage_id=record['usage_id'],usage_input=record['input'],
                exchanger_id=equipment['heat_exchanger_id'], inspection_id=inspection['iris_inspection_id'],
                scopes=[(s['equipment']['heat_exchanger_id'], s['inspection']['iris_inspection_id']) for s in scopes] if multi else None))
            app.logger.info('Text-to-SQL generated actor=%s exchanger=%s inspection=%s',
                            profile['user_id'], equipment['heat_exchanger_id'], inspection['iris_inspection_id'])
            return jsonify(proposal=proposal, token=token, equipment=equipment, inspection=inspection,
                           scopes=scopes, excluded=excluded, period=period,
                           query_kind='wall_loss_exchanger_count' if grouped_count else None)
        except Exception as exc:
            return fail(exc)

    @app.post('/inspections/text-to-sql/execute')
    def text_to_sql_execute():
        record = usage_record()
        profile = authorize()
        try:
            token = body().get('token')
            if not isinstance(token, str) or len(token) > 16000:
                raise QueryRejected('먼저 SQL을 생성하세요.')
            try:
                signed = serializer().loads(token, max_age=900)
            except SignatureExpired as exc:
                expired = serializer().loads(token)
                if expired.get('actor') == profile['user_id']:
                    signed_usage(expired)
                raise QueryRejected('SQL이 변경되었거나 15분이 지났습니다. 다시 생성하세요.') from exc
            except BadSignature as exc:
                raise QueryRejected('SQL이 변경되었거나 15분이 지났습니다. 다시 생성하세요.') from exc
            if signed['actor'] != profile['user_id']:
                raise PermissionError('다른 사용자가 생성한 SQL은 실행할 수 없습니다.')
            signed_usage(signed)
            if signed.get('query_kind') == 'equipment_analysis':
                if not all(services.user_can(profile,key) for key in ('REMAINING_LIFE','EXCHANGERS')):
                    raise PermissionError('열교환기·잔여수명 조회 권한이 필요합니다.')
                catalog=analysis.catalog()
                result=equipment_query.execute(signed['ids'],signed['settings'],signed['proposal'],
                    {r['heat_exchanger_id'] for r in catalog})
                record_scopes([dict(equipment=r,inspection=None) for r in catalog if r['heat_exchanger_id'] in signed['ids']])
                facts=result.pop('_commentary_facts',None) or commentary.evidence(result)
                result['summary_token']=serializer().dumps(dict(actor=profile['user_id'],
                    kind='result_commentary',ids=signed['ids'],facts=facts))
                record['result']={k:result.get(k) for k in ('result_count','query_sha256','limit_reached')}
                return jsonify(result=result)
            if signed.get('query_kind') == 'fluid_grouping':
                catalog = analysis.catalog()
                record_scopes([dict(equipment=row, inspection=None) for row in catalog
                               if row['heat_exchanger_id'] in signed['ids']])
                result = fluids.execute(signed['ids'], signed['settings'], signed['proposal'],
                                        {row['heat_exchanger_id'] for row in catalog})
                record['result'] = {key: result.get(key) for key in ('result_count','query_sha256','limit_reached')}
                return jsonify(result=result)
            if signed.get('period'):
                record['period'] = signed['period']
            if signed.get('query_kind') == 'inspection_frequency':
                catalog = analysis.catalog()
                allowed = {row['heat_exchanger_id'] for row in catalog}
                record_scopes([dict(equipment=row, inspection=None) for row in catalog
                               if row['heat_exchanger_id'] in signed['ids']])
                record['period'] = signed['period']
                result = frequency.execute(signed['ids'],signed['period'],signed['proposal'],allowed)
                record['result'] = {key: result.get(key) for key in ('result_count', 'query_sha256', 'limit_reached')}
                return jsonify(result=result)
            pairs = signed.get('scopes')
            if pairs:
                catalog = {row['heat_exchanger_id']: row for row in analysis.catalog()}
                allowed = frozenset(catalog)
                record_scopes([dict(equipment=catalog.get(i, dict(heat_exchanger_id=i)),
                    inspection=dict(iris_inspection_id=j)) for i, j in pairs])
                # Each signed pair is rechecked inside the read-only execution snapshot.
                equipment = dict(heat_exchanger_id=pairs[0][0])
                inspection = dict(iris_inspection_id=pairs[0][1])
            else:
                equipment, inspection, allowed = analysis.select_scope(
                    signed['exchanger_id'], signed['inspection_id'])
                record_scopes([dict(equipment=equipment, inspection=inspection)])
            validate_question_contract(signed['question'], signed['proposal'])
            options = dict(scopes=pairs) if pairs else {}
            if signed.get('period'):
                options['period'] = signed['period']
            result = execute_proposal(signed['proposal'], exchanger_id=equipment['heat_exchanger_id'],
                inspection_id=inspection['iris_inspection_id'], authorized_exchanger_ids=allowed, **options)
            if signed.get('query_kind') == 'wall_loss_exchanger_count':
                counts = {row['unit_code']: row['exchanger_count'] for row in result['rows']}
                result['rows'] = [dict(unit_code=unit, exchanger_count=counts.get(unit, 0))
                                  for unit in sorted(set(signed['group_units']))]
                result['result_count'] = len(result['rows'])
                result['limit_reached'] = False
                result['query_kind'] = 'wall_loss_exchanger_count'
                record['query_kind'] = result['query_kind']
            if signed.get('period'):
                result['period'] = signed['period']
            if result.get('scopes'):
                record_scopes(result['scopes'])
            record['result'] = {key: result.get(key) for key in ('result_count', 'query_sha256', 'limit_reached')}
            app.logger.info('Text-to-SQL executed actor=%s exchanger=%s inspection=%s query=%s rows=%s',
                profile['user_id'], equipment['heat_exchanger_id'], inspection['iris_inspection_id'],
                result['query_sha256'], result['result_count'])
            return jsonify(result=result)
        except Exception as exc:
            return fail(exc)

    @app.post('/inspections/text-to-sql/summarize')
    def text_to_sql_summarize():
        profile=authorize()
        try:
            if not all(services.user_can(profile,key) for key in ('REMAINING_LIFE','EXCHANGERS')):
                raise PermissionError('열교환기·잔여수명 조회 권한이 필요합니다.')
            token=body().get('token')
            if not isinstance(token,str) or len(token)>24000:
                raise QueryRejected('먼저 결과를 조회하세요.')
            try:
                signed=serializer().loads(token,max_age=900)
            except (BadSignature,SignatureExpired) as exc:
                raise QueryRejected('조회 결과가 만료되었거나 변경되었습니다. 다시 조회하세요.') from exc
            if signed.get('actor')!=profile['user_id'] or signed.get('kind')!='result_commentary':
                raise PermissionError('본인이 조회한 결과만 요약할 수 있습니다.')
            if not set(signed['ids'])<={r['heat_exchanger_id'] for r in analysis.catalog()}:
                raise PermissionError('조회 범위가 변경되었습니다. 다시 조회하세요.')
            record=usage_record();record['query_kind']='result_commentary'
            if not g.get('text_sql_model_worker'):
                return enqueue_model(text_to_sql_summarize, profile)
            return jsonify(commentary=commentary.generate(signed['facts']))
        except Exception as exc:
            return fail(exc)

    @app.after_request
    def protect_text_to_sql_response(response):
        if request.endpoint and request.endpoint.startswith('text_to_sql'):
            response.headers['Cache-Control'] = 'no-store'
        if g.get('text_sql_queue_submission'):
            return response
        if request.endpoint in ('text_to_sql_generate', 'text_to_sql_execute', 'text_to_sql_summarize'):
            try:
                record = usage_record()
                payload = response.get_json(silent=True) or {}
                succeeded = 200 <= response.status_code < 300
                record.update(status='success' if succeeded else 'error',
                    http_status=response.status_code,
                    duration_ms=round((time.monotonic() - g.text_sql_started) * 1000, 3),
                    error=(dict(type=record.pop('error_type', 'HTTPError'),
                        message=payload.get('error') or HTTPStatus(response.status_code).phrase)
                        if not succeeded else None))
                directory = app.config.get('TEXT_TO_SQL_USAGE_LOG_DIR') or (
                    APP_DIR / 'tmp' / 'text_to_sql-test-usage' if app.testing
                    else APP_DIR / 'logs' / 'text_to_sql')
                usage_log.append_usage(record, directory=directory)
                response.headers['X-Text-to-SQL-Usage-ID'] = record['usage_id']
            except Exception as exc:
                # Raw exception strings may contain database credentials or paths.
                app.logger.error('Text-to-SQL usage history write failed (%s)', type(exc).__name__)
                if response.status_code < 400:
                    response = jsonify(error='사용 이력을 저장하지 못했습니다. 잠시 후 다시 시도하거나 관리자에게 문의하세요.')
                    response.status_code = 503
                    response.headers['Cache-Control'] = 'no-store'
        return response
