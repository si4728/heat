from flask import Response, abort, current_app, render_template, request, url_for

from ...application.access_audit import audit_rows, export_csv


def register_routes(app):
    @app.get('/settings/access-logs')
    def access_logs():
        try:
            data = audit_rows(request.args,page=int(request.args.get('page','1')))
        except ValueError as error:
            abort(400,description=str(error))
        def page_url(page):
            return url_for('access_logs',**dict(data['filters'],page=page))
        return render_template('access_logs.html',**data,page_url=page_url,
            csv_url=url_for('access_logs_export',**data['filters']),
            audit_state=current_app.extensions['access_audit'])

    @app.get('/settings/access-logs/export.csv')
    def access_logs_export():
        try:
            data = audit_rows(request.args,export=True)
        except ValueError as error:
            abort(400,description=str(error))
        response = Response(export_csv(data['rows']),content_type='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = 'attachment; filename="iris2-access-logs.csv"'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Export-Truncated'] = str(data['truncated']).lower()
        return response
