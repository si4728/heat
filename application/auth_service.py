from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from ..hx_configuration import DB_PATH
from ..iris_v2_database import session_scope
from ..iris_v2_models import AppUser, UserScreenPermission


SCREEN_DEFINITIONS = (
    ("DASHBOARD", "대시보드", "운영 현황과 주요 지표"),
    ("EXCHANGERS", "열교환기 관리", "열교환기 목록·상세·등록·수정·Tube Map"),
    ("REMAINING_LIFE", "Tube Plugging/API 510", "Tube Plugging 예측 및 API 510 계산 관리"),
    ("INSPECTIONS", "검사 관리", "검사 이력·튜브별 이력·검사계획·PDF 보고서"),
    ("MAINTENANCE", "정비 관리", "작업지시와 정비·교체 이력"),
    ("QUALITY", "품질 이슈", "데이터 품질 이슈 조회"),
    ("PLANT_LINES", "조직 코드 설정", "공장·생산팀·공정의 코드와 Label 관리"),
    ("WALL_LOSS_COLORS", "Wall Loss 색상 설정", "2D/3D 감육 색상표"),
    ("JSON_IMPORT", "JSON 로드", "IRIS JSON 검증과 적재"),
    ("EXCEL_EXPORT", "Excel Export", "열교환기·튜브·검사 이력 다운로드"),
)
SCREEN_KEYS = {key for key, _label, _description in SCREEN_DEFINITIONS}
PDF_OPEN_MODES = {"CURRENT", "NEW"}


def _pdf_open_mode(value: Any, default: str = "NEW") -> str:
    mode = str(value or default).strip().upper()
    if mode not in PDF_OPEN_MODES:
        raise ValueError("PDF 열기 방식은 현재 창 또는 새 창(탭)만 선택할 수 있습니다.")
    return mode


def user_count() -> int:
    with session_scope(DB_PATH) as session:
        return session.scalar(
            select(func.count()).select_from(AppUser).where(AppUser.is_active.is_(True))
        ) or 0


def _validate_username(value: Any) -> str:
    username = str(value or "").strip().lower()
    if len(username) > 50 or username.count("@") != 1:
        raise ValueError("사용자 ID는 50자 이내의 올바른 이메일 주소로 입력해 주세요.")
    local_part, domain = username.split("@")
    local_valid = (
        bool(local_part)
        and not local_part.startswith(".")
        and not local_part.endswith(".")
        and ".." not in local_part
        and bool(re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local_part))
    )
    domain_labels = domain.split(".")
    domain_valid = len(domain_labels) >= 2 and all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in domain_labels
    )
    if not local_valid or not domain_valid:
        raise ValueError("사용자 ID는 50자 이내의 올바른 이메일 주소로 입력해 주세요.")
    return username


def _validate_password(password: Any) -> str:
    value = str(password or "")
    if len(value) < 9:
        raise ValueError("비밀번호는 문자 종류와 관계없이 9자 이상 입력해 주세요.")
    return value


def create_initial_admin(data: dict[str, Any]) -> dict[str, Any]:
    username = _validate_username(data.get("username"))
    display_name = str(data.get("display_name") or "").strip()
    password = _validate_password(data.get("password"))
    if password != str(data.get("password_confirm") or ""):
        raise ValueError("비밀번호 확인이 일치하지 않습니다.")
    if not display_name:
        raise ValueError("관리자 이름은 필수입니다.")
    with session_scope(DB_PATH) as session:
        if session.scalar(
            select(func.count()).select_from(AppUser).where(AppUser.is_active.is_(True))
        ):
            raise ValueError("초기 관리자가 이미 생성되어 있습니다.")
        user = AppUser(
            username=username,
            display_name=display_name,
            password_hash=generate_password_hash(password),
            is_admin=True,
            is_active=True,
        )
        session.add(user)
        session.flush()
        return {"user_id": user.user_id, "username": user.username,
                "display_name": user.display_name, "is_admin": True}


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    normalized = str(username or "").strip().lower()
    with session_scope(DB_PATH) as session:
        user = session.scalar(select(AppUser).where(AppUser.username == normalized))
        if not user or not user.is_active or not check_password_hash(user.password_hash, password or ""):
            return None
        user.last_login_at = datetime.now()
        return {"user_id": user.user_id, "username": user.username,
                "display_name": user.display_name, "is_admin": bool(user.is_admin),
                "is_active": bool(user.is_active)}


def user_access_profile(user_id: int) -> dict[str, Any] | None:
    with session_scope(DB_PATH) as session:
        user = session.get(AppUser, user_id)
        if not user or not user.is_active:
            return None
        permissions = {
            permission.screen_key: {
                "can_view": bool(permission.can_view),
                "can_edit": bool(permission.can_edit),
            }
            for permission in user.permissions
        }
        return {"user_id": user.user_id, "username": user.username,
                "display_name": user.display_name, "is_admin": bool(user.is_admin),
                "is_active": bool(user.is_active),
                "pdf_open_mode": user.pdf_open_mode or "NEW",
                "permissions": permissions}


def user_can(profile: dict[str, Any] | None, screen_key: str,
             edit: bool = False) -> bool:
    if not profile:
        return False
    if screen_key == "PDF_OCR_REVIEW":
        return bool(profile.get("is_active")) and str(profile.get("username") or "").strip().lower() == "silicon@gmail.com"
    if profile.get("is_admin"):
        return True
    permission = profile.get("permissions", {}).get(screen_key, {})
    return bool(permission.get("can_edit" if edit else "can_view"))


def users_management_data(edit_user_id: int | None = None) -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        users = session.scalars(select(AppUser).order_by(AppUser.username)).all()
        editing_user = session.get(AppUser, edit_user_id) if edit_user_id else None
        editing_permissions = {
            permission.screen_key: permission
            for permission in (editing_user.permissions if editing_user else [])
        }
        return {"users": users, "editing_user": editing_user,
                "editing_permissions": editing_permissions,
                "screen_definitions": SCREEN_DEFINITIONS}


def save_user(data: dict[str, Any], user_id: int | None = None,
              actor_user_id: int | None = None) -> dict[str, Any]:
    username = _validate_username(data.get("username"))
    display_name = str(data.get("display_name") or "").strip()
    if not display_name:
        raise ValueError("사용자 이름은 필수입니다.")
    password = str(data.get("password") or "")
    if user_id is None or password:
        password = _validate_password(password)
        if password != str(data.get("password_confirm") or ""):
            raise ValueError("비밀번호 확인이 일치하지 않습니다.")
    with session_scope(DB_PATH) as session:
        conflict = session.scalar(select(AppUser).where(
            AppUser.username == username,
            AppUser.user_id != (user_id or 0),
        ))
        if conflict:
            raise ValueError("이미 사용 중인 사용자 ID입니다.")
        user = session.get(AppUser, user_id) if user_id else AppUser()
        if not user:
            raise ValueError("수정할 사용자를 찾을 수 없습니다.")
        if user_id is None:
            session.add(user)
        user.username = username
        user.display_name = display_name
        user.is_admin = str(data.get("is_admin") or "").lower() in {"1", "true", "on", "yes"}
        user.is_active = str(data.get("is_active") or "").lower() in {"1", "true", "on", "yes"}
        if user_id is None or data.get("pdf_open_mode") not in (None, ""):
            user.pdf_open_mode = _pdf_open_mode(data.get("pdf_open_mode"))
        if password:
            user.password_hash = generate_password_hash(password)
        if user_id and user.user_id == actor_user_id and (not user.is_admin or not user.is_active):
            raise ValueError("현재 로그인한 관리자 계정의 관리자 권한 또는 활성 상태는 해제할 수 없습니다.")
        if user_id and not user.is_admin:
            other_admin_count = session.scalar(
                select(func.count()).select_from(AppUser).where(
                    AppUser.is_admin.is_(True), AppUser.is_active.is_(True),
                    AppUser.user_id != user.user_id,
                )
            ) or 0
            if not other_admin_count:
                raise ValueError("최소 한 명의 활성 관리자가 필요합니다.")
        session.flush()
        existing = {permission.screen_key: permission for permission in user.permissions}
        for screen_key in SCREEN_KEYS:
            can_edit = str(data.get(f"permission_{screen_key}_edit") or "").lower() in {
                "1", "true", "on", "yes"
            }
            can_view = can_edit or str(data.get(f"permission_{screen_key}_view") or "").lower() in {
                "1", "true", "on", "yes"
            }
            permission = existing.get(screen_key)
            if permission is None:
                permission = UserScreenPermission(user_id=user.user_id, screen_key=screen_key)
                session.add(permission)
            permission.can_view = can_view
            permission.can_edit = can_edit
        session.flush()
        return {"user_id": user.user_id, "username": user.username,
                "created": user_id is None}


def save_user_preferences(user_id: int, data: dict[str, Any]) -> dict[str, str]:
    mode = _pdf_open_mode(data.get("pdf_open_mode"))
    with session_scope(DB_PATH) as session:
        user = session.get(AppUser, user_id)
        if not user or not user.is_active:
            raise ValueError("설정을 저장할 사용자를 찾을 수 없습니다.")
        user.pdf_open_mode = mode
        return {"pdf_open_mode": mode}
