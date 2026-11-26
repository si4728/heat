# 보안 점검 및 1차 수정 결과 — 2026-11-26

접속 범위는 사용자의 최종 확인에 따라 **사외 모바일에서 인터넷 주소로 직접 접속**하는 환경이다. HTTPS는 미설정이며, Windows 웹 서버 실행 계정과 실제 외부 접속 주소는 아직 확정되지 않았다. 운영 포트 4824는 중단 상태를 유지했다. PE·VCM1·VCM2 기능을 대상으로 검사했으며 원본 iris는 변경하지 않았다.

## 항목별 결과

| 번호 | 우선순위 | 확인 내용·영향 | 처리 및 남은 작업 |
|---|---|---|---|
| SEC-01 | 긴급 | 기존 계정이 모두 비활성화되면 비로그인 초기 관리자 등록이 다시 열림. 임시 DB에서 계정 5→6 증가 재현 | **수정**. 전체 계정 존재 여부로 판단하고, 신규 설치의 초기 등록은 loopback IP와 localhost Host 조합만 허용. 단일 프로세스 초기 생성 직렬화. 현재 재검사 5→5, 등록 차단 |
| SEC-02 | 높음 | 관리자 비밀번호 변경 후 이전 로그인 쿠키로 관리자 화면 200 재현 | **수정**. 현재 비밀번호 해시에서 HMAC 인증 표식을 만들고 매 요청 검증. 이전 쿠키·표식 없는 쿠키는 로그인으로 이동. 기존 로그인도 다시 해야 함 |
| SEC-03 | 높음 | 로그인 반복 시도 제한 부재, 인증 요청 본문·자격 증명 길이 비용 제한 미흡 | **수정**. 300초 동안 IP+사용자 조합 5회, IP 합계 30회 제한. 진행 중 시도도 포함, 429와 Retry-After 반환. 인증 본문 16KB, 로그인 ID 50자·비밀번호 1024자 상한. 미존재 계정에도 더미 해시 검사 |
| SEC-04 | 보통 | 로그인 next 및 튜브 위치 저장 후 Referer를 통한 외부 이동 위험 | **수정**. 로컬 경로 및 명시된 동일 origin만 허용. 역슬래시·제어 문자·인코딩된 외부 authority 거부 |
| SEC-05 | 높음 | 잘못된 배포 설정으로 인증 비활성화 또는 debug 실행 가능 | **수정**. TESTING을 명시한 테스트 외에는 시작 거부. HTTPS 필수 설정과 비보안 쿠키의 불일치도 시작 거부 |
| SEC-06 | 보통 | 동적 화면 캐시·프레임 삽입·MIME 해석 등에 대한 공통 응답 정책 미흡 | **수정**. no-store, nosniff, SAMEORIGIN, same-origin referrer, CSP frame-ancestors/base-uri/form-action 적용. HTTPS 응답에만 HSTS. **전체 script-src CSP나 XSS 전수 검증 완료를 의미하지 않음** |
| SEC-07 | 보통 | 비로그인 /api/health 호출마다 전체 FK 무결성 검사, DB 버전·스키마 정보 공개 | **수정**. 현재 스키마 준비 상태만 1개 제한 조회, 앱별 2초 캐시·동시 요청 직렬화. 공개 응답은 application/backend/status만 제공. 상세 무결성 검사는 기존 관리자 DB 화면에서 유지 |
| SEC-08 | 낮음 | 비ASCII CSRF 값 비교 시 TypeError로 500 가능 | **수정**. 자료형 확인 및 UTF-8 바이트 상수시간 비교로 400 거부. 쓰기 API 토큰 비교도 UTF-8 상수시간 처리 |
| SEC-09 | 긴급 | 사외 직접 접속인데 HTTPS 미설정. 현재 Secure 쿠키 false, 허용 Host·신뢰 프록시 미설정 | **운영 적용 필요**. HTTPS 강제·Secure 쿠키·허용 Host·정확한 프록시 IP를 지원하는 코드는 추가했으나 실제 설정은 활성화하지 않음. 외부 주소·인증서·프록시 구성 필요 |
| SEC-10 | 긴급 | 세션 서명키·DB 설정 파일과 코드·가상환경·상위 폴더에 Everyone/Authenticated Users/Users의 읽기 또는 수정 허용 규칙 확인 | **운영 적용 필요**. 일반 로컬 사용자가 비공개 설정을 읽거나 코드/키를 교체할 수 있는 권한 구성. 실행 계정·관리자 복구 경로를 확정해 상위 폴더부터 제한. 개별 비밀 파일만 잠가서는 충분하지 않음. ACL 백업 완료, 권한 미변경 |
| SEC-11 | 높음 | 앱·읽기 계정에 이전 테스트·복원 스키마 권한 잔존. Text-to-SQL 계정에도 이전 테스트 스키마 전체 SELECT 존재 | **정리 필요**. 현재 필요한 운영 테이블 권한과 분리해 이전 테스트/복원 스키마 권한만 검토·회수해야 함. 이 점검에서 GRANT/REVOKE 미실행. 이전 승인으로 추가된 운영 이력 2개 테이블 SELECT는 유지 대상 |
| SEC-12 | 높음 | 로그아웃 전 복사한 쿠키를 다른 클라이언트에서 재사용하면 관리자 화면 200 재현 | **구조 보완 필요**. 비밀번호 변경 시 폐기는 해결했으나 일반 로그아웃은 현재 브라우저 쿠키만 삭제. DB에 개별 세션 등록/폐기·만료 상태를 저장하고 매 요청 확인하는 별도 마이그레이션 필요. 현재의 활동 기반 30분 제한만으로 복사 쿠키의 즉시 폐기를 보장할 수 없음 |
| SEC-13 | 보통 | 앱 로그인 제한은 단일 프로세스 메모리 기반. 재시작 시 초기화, 인터넷 다수 IP·연결 고갈 공격에 대한 전체 경계 아님 | **배포 보완 필요**. 프록시에서 요청 속도·연결·시간 제한, 실패 로그 감시. 다중 프로세스로 전환한다면 공유 제한 저장소와 초기 관리자 DB 잠금도 필요 |
| SEC-14 | 미확인 | Windows 방화벽 프로필은 켜져 있으나 개별 포트 규칙의 조회는 OS 접근 거부. 외부 공유기 NAT·포트포워딩과 TLS 장비도 미확인 | **추가 확인**. 포트 공개 범위, 관리 경로, DB 접근 차단을 실제 관리자/네트워크 설정에서 확인. 포트 규칙이 안전하다고 판정하지 않음 |

## SQL injection·권한·파일 경로 점검 범위

로그인은 SQLAlchemy 조건 바인딩을 사용한다. 임시 MariaDB에서 로그인 ID/비밀번호의 SQL 형태 입력으로 인증 우회가 발생하지 않았으며, 테이블 수와 계정 수가 유지됐다. Text-to-SQL의 바인딩 문자열에 OR/주석/DROP 형태 문장을 넣어도 값으로만 처리되어 0건이었다. 허용되지 않은 열교환기 ID는 DB 연결 전에 거부됐다.

모델 SQL 검증은 sqlglot AST 허용 목록, 서버가 정하는 analysis_tubes 범위, 바인딩, 전용 SELECT 계정, 읽기 트랜잭션, 5초 문장 제한과 최대 100행을 사용한다. 계정 테이블 접근·다중 문장·SLEEP·LOAD_FILE·UNION·주석을 포함하는 별도 6개 공격 입력은 모두 실행 전에 차단됐다. 기존 SQL 검증·미리보기 서명·사용자 소유권·화면 권한 회귀 검사도 통과했다. **이 결과는 점검한 경로의 결과이며 전체 시스템에 취약점이 없다는 보증은 아니다.**

현재 쓰기 API는 토큰 미설정으로 비활성화 상태다. PDF 연도/공정 형식 및 resolve 후 상위 경로 검사, 백업 파일 경계 검사도 코드에서 확인했다. 외부 TLS 인증서, 네트워크 침투 시험, 전체 의존성 CVE 대조, 업로드 파일 전반과 모든 JavaScript sink의 전수 XSS 검사는 이번 완료 범위에 포함하지 않았다.

## 재현·검증

운영 데이터는 읽기 복사만 하고, 변경 실험은 tests/customer_clone.py로 만드는 일회용 MariaDB에서 실행했다. 임시 SELECT 계정과 임시 웹 포트도 종료 시 제거했다. 비밀번호·쿠키·키·DB 연결 문자열은 보고서 또는 Git에 저장하지 않았다.

- 기존 고객 요구 회귀 검사: **286건 통과**. HTTP 변경 후 실행.
- 보안 검사: **18건 통과**. 초기 관리자·비밀번호 변경 세션·반복 로그인·실제 Waitress 신뢰 프록시·HTTPS/Host·보안 헤더·Unicode CSRF·공개 health·MariaDB SQL 입력 검증 포함.
- 초기 기동/격리 검사: **7건 통과**. health 실패 비공개 정보 제거 포함.
- 실제 Chrome: 로그인 화면 390/768/1440px, 390px 모바일 비밀번호 로그인과 Text-to-SQL 화면, 가로 넘침 없음, CSRF 실패 400, 정상 로그아웃 후 로그인 이동, 연속 실패 6번째 429. 로그인 후 응답 보안 헤더도 확인.
- 실제 Waitress 임시 리스너: 신뢰 프록시 없음/다른 IP인 경우 전달 IP·HTTPS 위조 무시, 정확한 프록시 IP인 경우만 처리. X-Forwarded-Host는 신뢰하지 않음.
- 현재 재현 보고서: 초기 관리자 재개방 false, 비밀번호 변경 후 이전 세션 false, **로그아웃 후 복사 쿠키 재사용 true**.

로컬 상세 증거는 Git 제외 경로인 reports/security-review-20261126/ 아래 baseline.json, current-validation.json, environment.json, acl-*.json, browser/checks.json 및 화면 PNG에 있다. baseline.json은 수정 전 증거로 보존했다.

실행 명령은 iris2 루트 기준이다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_security_*.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_bootstrap.py' -v
.\.venv\Scripts\python.exe tools/run_request_audit_tests.py
.\.venv\Scripts\python.exe tools/audit_security_baseline_20261126.py
.\.venv\Scripts\python.exe tools/audit_security_environment_20261126.py
.\.venv\Scripts\python.exe tools/verify_security_browser.py
```

## 다음 적용 순서·영향·복구

1. **외부 HTTPS**: 실제 접속 주소와 DNS/NAT 경로 확인 → 신뢰 가능한 인증서 설치 → TLS 종료 프록시 설정 → 백엔드는 127.0.0.1:4824에 바인딩하고 외부 직접 접근 차단 → 프록시는 사용자 전달 헤더를 덮어쓰고 고정 Host를 전달 → 앱의 HTTPS/Secure/Host/프록시 설정을 함께 적용 → 사내 PC와 실제 사외 모바일에서 검증. HTTP 접속은 프록시에서 HTTPS로 이동. /setup-admin은 외부 프록시에서 항상 차단하고 최초 설치는 로컬에서 수행. HTTPS 필수 설정만 먼저 켜면 기존 HTTP 접속이 400이 되므로 순서 준수.
2. **Windows 실행 계정·ACL**: 서비스·작업 스케줄러에서 iris2 자동 실행 항목을 찾지 못했다. 실행 계정 확인 후 Administrators/SYSTEM/배포 담당자/서비스 계정 접근을 구분한다. 서비스 계정은 소스·환경·설정 읽기, 필요한 런타임 폴더만 수정하도록 구성한다. 웹 프로세스가 DB 관리자 설정을 읽지 않도록 유지보수 계정/경로도 분리 검토한다. 루트 및 부모 폴더의 교체·삭제 권한도 관리자와 확인해야 한다. iris2 밖의 iris는 변경하지 않는다.
3. **세션 즉시 폐기**: 세션 ID를 DB에 등록하고 로그아웃을 필수 DB 트랜잭션으로 폐기한다. 재시작·복사 쿠키·동시 로그아웃/요청·DB 장애에서 폐기를 검증하고 보존/만료 정책을 정한다. 단순 메모리 차단 목록이나 마지막 로그인 시각 재활용으로 완료 처리하지 않는다.
4. **DB 최소 권한**: 사용 중인 앱/보조 3개 스키마와 Text-to-SQL 운영 테이블을 기준으로 정확한 회수 목록을 작성한다. SHOW GRANTS 원문은 인증 정보가 포함될 수 있어 공개하지 않는다. 별도 보안 백업 후 이전 테스트/복원 스키마 권한만 회수하고 조회 8종·정비·백업 복원 절차를 재검증한다. 실제 테스트는 임시 계정 사용으로 전환해 운영 계정의 테스트 스키마 권한이 재추가되지 않도록 한다.
5. **후속 점검**: 방화벽/NAT·인증 실패 감시·프록시 속도 제한, 의존성 보안 업데이트, XSS/업로드 전체 경로 점검을 완료한다.

HTTPS를 처리하는 로컬 프록시가 127.0.0.1인 경우의 **설정 형식 예시**이며 실제 주소를 뜻하지 않는다. 현재 파일에는 활성화하지 않았다.

```ini
[application]
session_cookie_secure = true

[security]
require_https = true
trusted_hosts = iris.example.com
trusted_proxy = 127.0.0.1
```

trusted_hosts에는 실제 접속 호스트만 지정한다. trusted_proxy는 와일드카드 없이 실제 1개 IP만 허용한다. 현재 구현은 1단 프록시 구성용이다. 앱의 HTTPS 판단은 신뢰하는 프록시가 X-Forwarded-Proto를 올바르게 설정해야 한다. 이 변경은 TLS 서버나 인증서를 자동 설치하지 않는다.

ACL 복구 도구는 고정 대상의 접근 ACL만 백업·복구한다. 파일 내용·소유권·감사 SACL은 복사하지 않는다. 기본 Backup 모드는 권한을 수정하지 않으며, Restore는 같은 PC·같은 workspace의 스냅샷만 허용한다. 선택 파일만 다루는 복구 도구이므로 전체 배포 폴더 ACL 변경의 완전한 복구본으로 사용해서는 안 된다. 전체 경로를 변경한다면 그 범위 전체의 별도 ACL 백업이 필요하다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/backup_windows_security_acl.ps1 -Mode Backup
# 먼저 복구 대상만 미리 보기. Snapshot에는 실제 생성된 로컬 ACL 백업 경로 사용.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/backup_windows_security_acl.ps1 -Mode Restore -Snapshot reports/security-review-20261126/acl-YYYYMMDD-HHMMSS.json -WhatIf
```

ExecutionPolicy 옵션은 해당 점검 프로세스에만 적용하며 시스템 정책을 변경하지 않는다. 실제 복구는 실행 계정·백업 내용을 검토한 뒤 수행한다. 이 점검에서는 복구 또는 권한 제한 명령을 실행하지 않았다. DB 비밀번호와 세션키는 권한 정리 후 교체 계획도 수립해야 하며, 이전 유출 여부를 단정하지 않는다.

배포 전/후에는 설정과 소스 버전을 함께 보존한다. 코드 롤백으로 SEC-01/02 취약점이 재도입될 수 있으므로 단순 이전 커밋 복원은 피한다. 키 변경 또는 이번 인증 표식 적용 후에는 사용자 재로그인이 필요하다. Git 소스 반영은 인증서·DB 계정·운영 설정 변경 또는 서버 재시작을 대신하지 않는다.

## 참고한 공식 문서

쿠키 및 응답 보안 정책은 [Flask Web Security](https://flask.palletsprojects.com/en/stable/web-security/), 허용 호스트 설정은 [Flask Configuration](https://flask.palletsprojects.com/en/stable/config/)을 참고했다. 프록시 신뢰 범위와 요청 제한은 [Waitress Arguments](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html), SQL 입력과 쿼리 구조 분리 점검은 [OWASP SQL Injection](https://community.owasp.org/attacks/SQL_Injection)을 참고했다.
