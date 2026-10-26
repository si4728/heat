# Source provenance

- 반입일: 2026-08-24
- 원본 프로젝트: `C:\access\llm`
- 대상 프로젝트: `C:\access\heat\iris2\llm_integration`

| 원본 | SHA-256 | 사용 방식 |
|---|---|---|
| `C:\access\llm\multi_model_dialogue.py` | `13FC0693158785122CAE05AF19383717A69696C065F2EE6B3BEB23A0CAD57831` | 원본 사본 보관, 로컬 Client/Cache 패턴 참고 |
| `C:\access\llm\models.json` | `34FAAC9E8C0CE5A4117D10F3D8E2B02D184A84626156D582AB27DA44EAE47309` | 직접 복사하지 않음, 외부 Provider 제거 후 예시 설정 작성 |
| `C:\access\llm\reports\PRODUCTION_HARDENING_CHECKLIST.md` | `9062E5B01E40CDE6F332118030BFFF42079DD3D8F44326B22104EEB7CD99B2E5` | 원본 사본 보관, 운영 점검 참고 |

## Adopted

- llama.cpp GGUF 직접 로딩
- Lazy loading과 bounded keep-loaded cache
- 요청 직렬화
- Thread/Batch/GPU layer 환경 설정
- Chat Completion 호출 구조

## Excluded

- `models.json`의 Gemini Provider
- 외부 API 호출 코드와 Cloud SDK
- 개인 사용자 홈의 LM Studio 모델 절대경로
- 원본 프로젝트의 사용자/세션/업무 DB
- 음성 및 코드 개발 기능

Curated module은 원본을 그대로 실행하는 대신 IRIS 요구사항에 맞춰 Provider Allowlist,
상대/환경변수 모델 경로, 명시적 종료 및 입력 검증을 추가한 파생 구현이다.
