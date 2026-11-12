from __future__ import annotations

import threading
from iris2 import dbapi

from flask import abort, g, jsonify, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from iris2 import services
from iris2.application import text_to_sql_service as analysis
from iris2.application import inspection_frequency as frequency
from iris2.llm_integration.text_to_sql import (
    QueryRejected, execute_proposal, validate_proposal, validate_question_contract,
)


def register_routes(app):
    generation_lock = threading.Lock()

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
                raise PermissionError('VCM1·VCM2 범위의 설비를 선택하세요.')
            return jsonify(inspections=analysis.inspections(exchanger_id))
        except Exception as exc:
            return fail(exc)

    @app.post('/inspections/text-to-sql/generate')
    def text_to_sql_generate():
        profile = authorize()
        try:
            data = body()
            question = data.get('question')
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
                raise QueryRejected('질문은 1~500자로 입력하세요.')
            if frequency.matches(question):
                catalog = analysis.catalog()
                ids = data.get('exchanger_ids')
                units = data.get('unit_codes')
                if 'exchanger_id' in data:
                    if ids is not None or units is not None:
                        raise QueryRejected('조회 범위 선택 방식을 하나만 지정하세요.')
                    ids = [identifier(data['exchanger_id'])]
                if units is not None:
                    if ids is not None or not isinstance(units,list) or not units or any(u not in ('VCM1','VCM2') for u in units):
                        raise QueryRejected('VCM1·VCM2 공정 또는 교환기를 선택하세요.')
                    selected = [row for row in catalog if row['unit_code'] in units]
                elif ids is not None:
                    if not isinstance(ids,list) or not ids or any(type(i) is not int or i<=0 for i in ids):
                        raise QueryRejected('교환기를 선택하세요.')
                    if not set(ids)<={row['heat_exchanger_id'] for row in catalog}:
                        raise PermissionError('VCM1·VCM2 범위의 설비를 선택하세요.')
                    selected = [row for row in catalog if row['heat_exchanger_id'] in ids]
                else:
                    selected = catalog
                ids = [row['heat_exchanger_id'] for row in selected]
                period = frequency.options(question)
                proposal = frequency.proposal(ids,period)
                token = serializer().dumps(dict(actor=profile['user_id'],query_kind='inspection_frequency',
                    ids=ids,period=period,proposal=proposal))
                return jsonify(proposal=proposal,token=token,query_kind='inspection_frequency',period=period,
                               equipment_list=selected)
            multi = 'exchanger_ids' in data or 'unit_codes' in data
            if multi:
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
            if not generation_lock.acquire(blocking=False):
                return jsonify(error='다른 SQL을 생성 중입니다. 잠시 후 다시 시도하세요.'), 429
            try:
                proposal = analysis.generate_in_worker(question.strip())
            finally:
                generation_lock.release()
            sql, parameters = validate_proposal(proposal)
            validate_question_contract(question, proposal)
            proposal = dict(sql=sql, parameters=parameters)
            token = serializer().dumps(dict(
                actor=profile['user_id'], question=question.strip(), proposal=proposal,
                exchanger_id=equipment['heat_exchanger_id'], inspection_id=inspection['iris_inspection_id'],
                scopes=[(s['equipment']['heat_exchanger_id'], s['inspection']['iris_inspection_id']) for s in scopes] if multi else None))
            app.logger.info('Text-to-SQL generated actor=%s exchanger=%s inspection=%s',
                            profile['user_id'], equipment['heat_exchanger_id'], inspection['iris_inspection_id'])
            return jsonify(proposal=proposal, token=token, equipment=equipment, inspection=inspection,
                           scopes=scopes, excluded=excluded)
        except Exception as exc:
            return fail(exc)

    @app.post('/inspections/text-to-sql/execute')
    def text_to_sql_execute():
        profile = authorize()
        try:
            token = body().get('token')
            if not isinstance(token, str) or len(token) > 16000:
                raise QueryRejected('먼저 SQL을 생성하세요.')
            try:
                signed = serializer().loads(token, max_age=900)
            except (BadSignature, SignatureExpired) as exc:
                raise QueryRejected('SQL이 변경되었거나 15분이 지났습니다. 다시 생성하세요.') from exc
            if signed['actor'] != profile['user_id']:
                raise PermissionError('다른 사용자가 생성한 SQL은 실행할 수 없습니다.')
            if signed.get('query_kind') == 'inspection_frequency':
                allowed = {row['heat_exchanger_id'] for row in analysis.catalog()}
                return jsonify(result=frequency.execute(signed['ids'],signed['period'],signed['proposal'],allowed))
            pairs = signed.get('scopes')
            if pairs:
                allowed = frozenset(row['heat_exchanger_id'] for row in analysis.catalog())
                # Each signed pair is rechecked inside the read-only execution snapshot.
                equipment = dict(heat_exchanger_id=pairs[0][0])
                inspection = dict(iris_inspection_id=pairs[0][1])
            else:
                equipment, inspection, allowed = analysis.select_scope(
                    signed['exchanger_id'], signed['inspection_id'])
            validate_question_contract(signed['question'], signed['proposal'])
            options = dict(scopes=pairs) if pairs else {}
            result = execute_proposal(signed['proposal'], exchanger_id=equipment['heat_exchanger_id'],
                inspection_id=inspection['iris_inspection_id'], authorized_exchanger_ids=allowed, **options)
            app.logger.info('Text-to-SQL executed actor=%s exchanger=%s inspection=%s query=%s rows=%s',
                profile['user_id'], equipment['heat_exchanger_id'], inspection['iris_inspection_id'],
                result['query_sha256'], result['result_count'])
            return jsonify(result=result)
        except Exception as exc:
            return fail(exc)

    @app.after_request
    def protect_text_to_sql_response(response):
        if request.endpoint and request.endpoint.startswith('text_to_sql'):
            response.headers['Cache-Control'] = 'no-store'
        return response
