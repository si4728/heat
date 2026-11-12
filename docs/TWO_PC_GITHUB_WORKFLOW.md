# 운영·개발 두 PC의 GitHub 작업 절차

시행일: 2026-11-12. 공통 저장소: https://github.com/si4728/heat. 두 PC 모두 저장소 폴더 이름을 `iris2`로 유지한다. 운영 PC에서도 코드 수정이 가능하며, GitHub에 게시한 변경을 다른 PC가 받아서 이어서 작업한다.

## 작업 시작

각 PC에 Git을 설치하고 iris2 디렉터리에서 실행한다. 현재 PC의 로컬 수정이 없는 상태에서 다음 순서를 따른다.

```powershell
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c dev/20261112-task-name
```

운영 PC는 `ops/20261112-task-name`, 개발 PC는 `dev/20261112-task-name`처럼 중복되지 않는 작업 브랜치를 사용한다. 날짜와 task-name은 실제 작업에 맞춘다. 로컬 수정이 있으면 먼저 해당 작업 브랜치에 필요한 파일을 명시하여 커밋한다. pull 실패 시 reset/강제 덮어쓰기로 해결하지 않는다.

## 변경 게시와 통합

```powershell
.\.venv\Scripts\python.exe -m unittest llm_integration.tests.test_text_to_sql tests.test_text_to_sql_web tests.test_text_to_sql_scope tests.test_inspection_frequency -q
git diff --check
git add <변경한-소스와-시험과-문서-경로>
git diff --cached --stat
git commit -m "Describe the change"
git fetch origin
git merge origin/main
git push -u origin HEAD
```

예시 시험은 Text-to-SQL 변경용이다. 작업에 맞는 시험을 실행한다. 원격 통합으로 코드가 바뀌면 관련 시험을 다시 실행한다. GitHub에서 PR로 main에 통합한 뒤 다른 PC가 받는다. main 강제 push를 사용하지 않는다. 두 PC가 같은 파일을 바꾼 경우 두 변경의 목적을 보존해 충돌을 해결한다.

## 운영 반영

실행 중인 운영 파일을 수정할 경우 정비 시간을 확보한다. 먼저 로컬 수정과 배포 전 커밋을 확인하고 소스를 백업한다. 승인된 변경이 main에 통합된 뒤 깨끗한 운영 checkout에서 실행한다.

```powershell
git status --short --branch
git switch main
git pull --ff-only origin main
git log -1 --oneline
```

운영 PC의 변경이 남아 있으면 작업 브랜치에 보존·게시하고 통합을 마친 뒤 진행한다. Python 변경은 기존 운영 절차로 앱을 재시작하고 로그인·VCM1/VCM2 조회·Text-to-SQL을 확인한다. GitHub 게시와 운영 적용/재시작은 별개이다.

## 각 PC에 별도로 필요한 것

- `.venv`, MariaDB 실행 환경, 운영 데이터 및 업로드.
- `config/database.conf`, `config/database-admin.conf`, `config/database-readonly.conf`, `config/database-text-to-sql.conf`와 PC별 전용 계정·권한.
- `llm_integration/models.local.json`과 `data/llm/models/`의 GGUF 파일.
- 앱의 세션 키와 환경별 설정. 개발 PC의 값을 운영에 덮어쓰지 않는다.

비밀번호·API 키·세션 파일·DB 덤프·원본 업무 자료·생성 영상/보고서는 커밋하지 않는다. 필요한 산출물은 별도 관리한다. 저장소의 기존 익명화 snapshot은 일반 운영 DB 백업의 게시 허용을 의미하지 않는다.

## Text-to-SQL 이관 오류와 GitHub 변경

이전 ZIP 통합본에는 생성 워커와 모델 설정 파서가 빠져 있었으나, `tools/generate_text_to_sql.py`와 `llm_integration/model_config.py`는 이미 GitHub 추적 파일이다. 전체 저장소 동기화로 파일을 받는다. 전용 DB 설정은 GitHub에서 받지 않으며 각 PC에서 준비해야 한다.

2026-11-12 원격 기록에는 두 번째 PC의 전용 설정 누락과 MariaDB PUBLIC test-schema 권한 문제에 대한 조치가 기록되어 있다. [해당 PC의 DB 점검 기록](TEXT_TO_SQL_DB_CHECK_20261112.md)을 확인한다. 이 기록을 다른 PC의 상태가 동일하다는 뜻으로 해석하지 않는다. 계정 생성·권한 복구 도구는 DB를 변경하므로 환경 및 적용 필요성을 확인한 뒤 실행한다.
