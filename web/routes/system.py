from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for

from iris2 import services


def register_routes(app) -> None:
    @app.get("/settings/database-monitor")
    def database_monitor():
        return render_template(
            "database_monitor.html",
            monitor=services.database_monitor_data(),
        )

    @app.route("/settings/backups", methods=["GET", "POST"])
    def backup_manager():
        if request.method == "POST":
            action = request.form.get("action")
            try:
                if action == "save_schedule":
                    services.save_backup_schedule(request.form.to_dict())
                    flash("백업 설정을 저장했습니다.", "success")
                elif action == "run_now":
                    current_user = g.get("current_user") or {}
                    result = services.run_backup_now(current_user.get("username") or "administrator")
                    if result["status"] == "SUCCESS":
                        flash("DB 백업과 무결성 검사를 완료했습니다.", "success")
                    elif result["status"] == "SUCCESS_WITH_NOTE":
                        flash("백업은 완료했지만 오래된 파일 정리에 실패했습니다. 백업 로그를 확인해 주세요.", "warning")
                    else:
                        flash(f"백업을 완료하지 못했습니다: {result['error']}", "error")
                elif action == "restore":
                    current_user = g.get("current_user") or {}
                    result = services.restore_database(
                        request.form.get("backup_name") or "",
                        request.form.get("reason") or "",
                        current_user.get("username") or "administrator",
                    )
                    if result["status"] == "SUCCESS":
                        flash("백업을 별도 DB에 복원했습니다. 운영 DB 전환은 수행하지 않았습니다.", "success")
                    elif result["status"] == "SUCCESS_WITH_NOTE":
                        flash("별도 DB 복원과 구조 검증을 완료했습니다. 전체 데이터 대사는 추가 확인이 필요합니다.", "warning")
                    else:
                        flash(f"복구를 완료하지 못했습니다: {result['error']}", "error")
                else:
                    raise ValueError("지원하지 않는 백업 작업입니다.")
            except (RuntimeError, ValueError) as exc:
                flash(str(exc), "error")
            return redirect(url_for("backup_manager"))
        return render_template(
            "backup_manager.html",
            backup=services.backup_management_data(),
        )
