# Personal AI Office — Architecture

> 상태: Phase 1 (MVP) 구현 완료 + Phase 2 일부(멀티에이전트, Critic, 장기 실행 Job, Knowledge Base, Dashboard, 버전 관리, 픽셀 오피스 UI).

## 0. Repository 분석 결과

작업 시작 시점의 저장소는 **커밋이 없는 빈 저장소**였다. 재사용할 기존 코드가 없으므로
전체 구조를 새로 설계했다. 실행 환경: Python 3.11, Node 22, Docker 사용 가능.

## 1. Architecture

```
USER (CEO)
  │  자연어 명령 / DM / 결재
  ▼
Next.js 픽셀 오피스 UI ──REST + SSE──▶ FastAPI (backend/app)
                                         │
                ┌────────────────────────┼─────────────────────────┐
                ▼                        ▼                         ▼
          Task / Job queue         Office layer               Knowledge Base
      (DB-backed, worker 프로세스)  (직원·채널·메시지·         (문서·청크·표·
                │                   결재·회의·DM)             하이브리드 검색)
                ▼                        ▲
        Research-to-Artifact Pipeline ───┘ (모든 단계가 직원 대화/결재/회의로 기록)
   Plan → Research → Extract → Verify → Analyze → Critic(debate) → Write → Build → QC
                │
     Agents (전문 역할) ──▶ Tools (search, fetch, parse, calc, docx/pptx/xlsx) ──▶ Artifacts
                │
           Model Router ──▶ LLM Provider (Anthropic | Offline 결정론적 엔진)
```

핵심 규칙
* **Agent ≠ Tool.** 에이전트는 판단(LLM 프롬프트 + 규칙), 도구는 부작용이 있는 결정론적 함수.
* **검증은 결정론적으로.** 인용문이 원문에 실제로 존재하는지, 숫자가 인용문에 존재하는지,
  출처 날짜, 교차 출처, 충돌 여부를 코드로 검사한다. LLM의 “자신감”으로 verified 처리하지 않는다.
* **계산은 Python이 한다.** 재무 모델은 Python으로 계산하고, xlsx에는 동일한 수식을 기록한 뒤
  두 결과를 대조한다.
* **외부 텍스트는 모두 UNTRUSTED.** 웹/PDF/문서 텍스트는 `<untrusted_document>` 경계로 감싸고,
  인젝션 패턴을 탐지·중화하며, 그 안의 지시문은 실행하지 않는다.
* **모르면 UNKNOWN.** 근거가 없는 항목은 채우지 않고 UNKNOWN으로 표시한다.
* **실패를 숨기지 않는다.** 접근 실패 출처 수, 미검증 주장 수를 결과에 그대로 보고한다.

## 2. File structure

```
backend/
  app/
    main.py              FastAPI 앱 조립, 라우터, 시작 시 시드
    worker.py            백그라운드 Job 워커 (python -m app.worker)
    core/                config, db, models(ORM), security(인증·마스킹·인젝션), audit, files, events
    llm/                 provider 인터페이스, Anthropic provider, Offline provider, model router
    tools/               web_search(제공자들), fetch, source_rank, calc, registry, approval gate
    knowledge/           parsers(PDF/DOCX/PPTX/XLSX/TXT/MD/HTML/이미지 OCR), chunking, embeddings, hybrid search
    generators/          docx_builder, pptx_builder, xlsx_builder, export(pdf/csv/md/txt)
    agents/              base + 각 전문 에이전트(orchestrator, research, verification, business,
                         strategy, writing, presentation, data, critic, meeting, coding)
    pipeline/            research_to_artifact (핵심 workflow), qc 체크리스트
    office/              직원 로스터, 채널/메시지, 결재(approval chain), 회의, DM 응답
    jobs/                DB 기반 Job 큐
    plugins/             플러그인 인터페이스 + 레지스트리 (Google Drive, Notion, Slack, GitHub … 스텁 아님: 설정 없으면 비활성으로 보고)
    api/                 REST 라우터
  tests/                 pytest (citation, 검증, 문서 생성, 권한, 인젝션, 파싱, 오케스트레이션, E2E)
frontend/                Next.js + TypeScript + Tailwind, 픽셀아트 오피스
docs/                    이 문서
docker-compose.yml       api, worker, web (+ 선택적 postgres/redis 프로필)
```

## 3. Technology choices

| 영역 | 선택 | 이유 |
|---|---|---|
| API | FastAPI + Pydantic v2 | 타입, OpenAPI 자동 문서 |
| ORM/DB | SQLAlchemy 2.0, 기본 SQLite → `DATABASE_URL`로 PostgreSQL | MVP는 무설치, 운영은 Postgres |
| 벡터 | 청크 임베딩을 DB에 저장 + NumPy 코사인, BM25와 RRF 결합 | 외부 의존 없이 하이브리드 검색. pgvector로 교체 가능한 인터페이스 |
| 임베딩 | `EMBEDDING_PROVIDER=hash`(로컬 해싱, 기본) / `voyage` | 키 없이도 동작 |
| LLM | Anthropic SDK (`claude-opus-5`, `claude-haiku-4-5`) + Offline 엔진 | 키가 없으면 결정론적(추출 기반) 엔진으로 동작 — 생성은 보수적 |
| Job | DB 기반 큐 + 워커 프로세스(또는 API 내장 스레드) | Celery/Redis 없이 장기 작업. Redis 도입 시 동일 인터페이스 |
| 문서 | python-docx, python-pptx, openpyxl, PyMuPDF | 실제 파일 생성/파싱 |
| 실시간 | SSE (`/api/events/stream`) | 오피스 대화 라이브 스트림 |
| UI | Next.js 14 App Router, Tailwind, Canvas 픽셀아트 | 외부 에셋 없이 절차적 스프라이트 |

## 4. Database schema (주요 테이블)

* `users` — 인증 사용자 (PBKDF2 해시)
* `projects` — 워크스페이스 (폴더: research/documents/presentations/spreadsheets/source_files/final/archive)
* `tasks`, `task_steps` — 상태(BACKLOG…FAILED), 우선순위, 마감, 의존성, 참여 에이전트, 진행률
* `jobs` — 백그라운드 작업 큐 (queued/running/succeeded/failed)
* `sources` — 출처 (tier 1–7, 발행일, 접근일, 접근 성공 여부, KB 문서 링크)
* `claims` — 주장 (kind: FACT/ANALYSIS/ASSUMPTION/ESTIMATE/OPINION/UNKNOWN, supporting_quote, page_number, confidence, verification_status)
* `kb_documents`, `kb_chunks`, `kb_tables` — 지식베이스
* `artifacts`, `artifact_versions` — 결과물 및 버전(v1, v2 … final, 변경 노트)
* `approvals` — 결재 (risk LOW..CRITICAL, 결재선 stamps, 상태)
* `audit_logs` — 전체 행동 기록
* `memories` — 계층형 메모리 (explicit vs auto, 만료)
* `templates` — 문서/발표 템플릿
* `employees`, `channels`, `messages`, `meetings`, `action_items` — 픽셀 오피스
* `notifications`

## 5. Agent architecture

| 부서 | 직원(3+) | 에이전트 역할 |
|---|---|---|
| 경영지원실 | 실장(Orchestrator), 기획, 감사(Critic) | 업무 분해, 배정, 통합, 비판적 검토 |
| 리서치팀 | 팀장, 웹 리서처, 문서 분석가, 통계 | 검색, 원문 확인, 근거 추출 |
| 검증팀 | 팀장, 인용 담당, 숫자 감사 | 인용문·숫자·날짜·충돌 검증 |
| 전략사업팀 | 팀장(Strategy), 사업모델, 재무 | 분석, 시나리오, 재무 모델 |
| 문서팀 | 팀장(Writing), DOCX 담당, 교정 | 보고서/DOCX |
| 디자인팀 | 팀장(Presentation), 슬라이드, 시각화 | PPTX/차트 |
| 데이터·개발팀 | 팀장(Data), 분석가, 개발자(Coding) | XLSX, 계산 검증, 코드 |

각 단계는 담당 직원이 부서 채널에 보고 → 팀장 결재 → 실장 결재 → (HIGH 이상/최종 산출물) CEO(사용자) 결재 순으로 진행된다.
킥오프 회의와 리뷰 회의(Multi-Agent Debate)가 회의실 채널에 기록되고, 회의록은
Decision / Action Item / Owner / Deadline / Status 로 저장된다.

## 6. Tool architecture

`tools/registry.py`에 모든 도구가 `ToolSpec(name, risk, fn)`으로 등록된다.
`execute_tool()`은 (1) 위험도 판정 (2) HIGH 이상이면 승인 요청 생성 후 중단 (3) 감사 로그 기록 을 강제한다.
에이전트는 도구를 직접 import 하지 않고 레지스트리를 통해 호출한다.

## 7. MVP implementation plan (완료 체크)

1. [x] Chat/Command UI — 픽셀 오피스 하단 명령창 + 진행 상황
2. [x] Task system — 상태 머신, 단계, 진행률
3. [x] Orchestrator — 계획/분해/배정
4. [x] Web research — 제공자 인터페이스(Tavily/Brave/Serper/SearXNG/fixture), 원문 fetch
5. [x] Source management — 등급, 날짜, 접근 여부
6. [x] PDF/DOCX/PPTX/XLSX ingestion
7. [x] Citation system — [n] 인용, 클릭 시 출처 상세
8. [x] DOCX generation  9. [x] PPTX generation  10. [x] XLSX generation
11. [x] Basic verification + QC 체크리스트 + Critic 재조사 루프
12. [x] Project workspace  13. [x] File management + 버전 관리
