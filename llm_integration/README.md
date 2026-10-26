# IRIS local LLM integration staging area

이 폴더는 `C:\access\llm`에서 확인한 재사용 가능 요소를 IRIS 애플리케이션 경계
안으로 가져온 작업공간이다. 현재 Flask Route나 운영 DB에는 연결하지 않았으므로 이
폴더의 추가만으로 기존 IRIS 기능이나 시작 시간이 변경되지 않는다.

## Curated modules

- `model_config.py`: `llama_cpp`만 허용하는 오프라인 모델 설정 로더
- `local_llm.py`: GGUF 지연 로딩, bounded cache, 요청 직렬화 및 Chat Completion Client
- `models.local.example.json`: 현장 설치용 모델 설정 예시
- `requirements.txt`: 별도 오프라인 설치 대상

## Reference copies

- `reference/multi_model_dialogue.py`: 원본 로컬 모델 Client와 다중 모델 Workflow 참고본
- `reference/PRODUCTION_HARDENING_CHECKLIST.md`: 원본 운영 Hardening 참고본
- `reference/PROVENANCE.md`: 원본 위치, Hash, 채택/제외 범위

Reference 파일은 추적용 사본이며 IRIS에서 직접 import하지 않는다. 실제 통합에는
상위의 작은 Curated module만 사용한다.

## Explicit exclusions

- Gemini/OpenAI/Mistral 등 외부 API Provider
- API Key와 Cloud SDK
- `C:\access\llm`의 사용자 DB와 Session
- 음성 ASR/TTS
- 코드 생성 및 Sandbox 실행 기능
- 사용자 홈 또는 LM Studio에 종속된 모델 절대경로

## Integration gates

1. 고객 승인 GGUF 모델과 라이선스 확정
2. 모델 SHA-256 및 Release Manifest 등록
3. 현장 전용 `IRIS2_MODEL_DIR` 설정 (현재 `models.local.json`은 `C:\access\llm` 참고용 파일럿 모델 경로 사용)
4. 구조화 보고서 JSON Schema 및 근거 검증 구현
5. 생성 이력·검토·승인 DB Schema 구현
6. 외부 통신 0건 시험
7. 대상 PC 성능·메모리·장시간 실행시험
