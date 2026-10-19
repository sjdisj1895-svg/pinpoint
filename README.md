# PinPlay

지도 기반 로컬 여가·문화 큐레이션. 자연어 입력 → 의도 분석 → 실시간 로컬 데이터 검증 → 맞춤 추천/코스 → 지도 UI, 현장 변동 시 리라우팅.

## 구조

| 단계 | 모듈 | 역할 |
|---|---|---|
| T1 | `app/stages/t1_intent.py` | 사용자 입력 → 지역·시간·성향·카테고리 JSON |
| T2 | `app/stages/t2_harvester.py` | Raw Data 검증·정규화 (시점·위치·신뢰도) |
| T3 | `app/stages/t3_curator.py` | 핀 리스트 + 2~4곳 추천 코스 (거리는 코드로 검증) |
| T4 | `frontend/` | React + Leaflet 지도 UI: 사진 카드, 시기·분류 필터, 정렬, 더보기 (데스크탑 40/60, 모바일 바텀시트). 첫 화면은 경남 둘러보기 |
| T5 | `app/stages/t5_rerouter.py` | 날씨·지연·피드백 대응 부분 수정 (`POST /reroute`) |
| T6 | `app/connectors/`, `supabase/schema.sql` | 공공/검색 API 4종 + PostGIS 저장소 |

프롬프트는 `app/prompts/*.md`에 있습니다.

LLM은 두 방식 중 선택합니다 (`app/llm.py`).
- **OpenAI 호환 서비스:** `.env`에 `API_KEY`, `API_BASE`, `API_MODEL`을 모두 넣으면 자동 선택됩니다. 모든 단계가 `API_MODEL` 하나를 씁니다.
- **Claude:** 위 세 변수가 없으면 `ANTHROPIC_API_KEY`를 쓰고, 모델은 `PINPLAY_MODEL`(기본 `claude-opus-5-5`), Connector D 파서는 `PINPLAY_PARSER_MODEL`(기본 `claude-haiku-5-5`).
- `LLM_PROVIDER=anthropic|openai`로 강제할 수 있습니다. 프롬프트는 Claude로 작성·조정했으므로 다른 모델에서는 JSON 형식 준수율과 품질이 달라질 수 있습니다.

## 실행

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt   # 배포용 requirements.txt + 개발 도구(uvicorn, pytest)
copy .env.example .env        # 키 입력 (아래 표 참고)
cd frontend; npm install; npm run build; cd ..
.venv\Scripts\uvicorn app.main:app --port 8000
```

`http://localhost:8000` — 빌드된 프론트를 같은 서버가 서빙합니다. API는 `/pipeline` 또는 `/api/pipeline`처럼 루트와 `/api` 양쪽에서 동작하고, 문서는 `/docs`입니다.
`http://localhost:8000/?sample` 로 열면 키 없이 샘플 데이터로 화면을 볼 수 있습니다 (`&course`: 추천 코스 표시).

프론트 개발 모드: 터미널 2개 — `uvicorn app.main:app --reload`, `cd frontend; npm run dev` (Vite가 `/api`를 8000으로 프록시).
Node가 PATH에 없으면 `C:\Program Files\nodejs`를 PATH에 추가하세요.

## 키 (`.env`)

| 변수 | 발급처 | 용도 |
|---|---|---|
| `API_KEY`, `API_BASE`, `API_MODEL` | OpenAI 호환 서비스 | T1~T5, Connector D 파서 (둘 중 하나만 있으면 됨) |
| `ANTHROPIC_API_KEY` | console.anthropic.com | T1~T5, Connector D 파서 |
| `DATA_GO_KR_KEY` | data.go.kr — 한국관광공사 국문 관광정보(TourAPI 4.0), 전국문화축제표준데이터 활용신청 | Connector A, B (Decoding 키) |
| `KOBIS_KEY` | kobis.or.kr/kobisopenapi | Connector C 박스오피스 |
| `KAKAO_REST_KEY` | developers.kakao.com (카카오맵/로컬 사용 설정) | 영화관 검색, 지오코딩 |
| `KAKAO_JS_KEY` | 같은 앱의 JavaScript 키 + Web 플랫폼에 사이트 주소 등록 | 지도를 카카오맵으로 표시 (비면 OpenFreeMap) |
| `NAVER_CLIENT_ID/SECRET`, `NAVER_API_MODE` | 네이버 클라우드 API Hub(`hub`, 기본) 또는 developers.naver.com(`developers`)의 검색 API | Connector D |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | supabase.com | 공간 DB (서버 전용 키) |
| `ADMIN_TOKEN` | 직접 생성 | `POST /harvest` 보호 (비우면 비활성) |

키가 일부만 있어도 동작합니다. 없는 소스는 건너뛰고 `/harvest` 응답의 `skipped`에 표시됩니다. 키가 하나도 없으면 T2 결과가 빈 배열입니다.

## 데이터 레이어

1. Supabase SQL Editor에서 `supabase/schema.sql` 실행 (PostGIS, `spots` 테이블, `search_spots_nearby`, `upsert_spots`).
2. 수집: `POST /harvest` (헤더 `X-Admin-Token`) 또는 `python -m scripts.harvest_regions` (정기 실행은 작업 스케줄러/cron).
3. `/pipeline`의 T2는 DB를 먼저 조회하고, 비어 있으면 수집·저장 후 다시 조회합니다. `GET /spots/search`는 저장된 데이터만 조회합니다.

### 경남 특화

- **수집:** `scripts/regions.json`에 경남 18개 시·군(창원·진주·김해·통영·거제·양산·사천·밀양·하동·남해·함안·창녕·고성·산청·함양·거창·합천·의령)이 `"province": "경남"`으로 들어 있습니다.
  ```powershell
  .venv\Scripts\python -m scripts.harvest_regions --province 경남                              # 오늘 기준 전체(관광지·영화관·네이버 포함)
  .venv\Scripts\python -m scripts.harvest_regions --province 경남 --festival-only --offsets 21,30,45,60,90   # 개최예정 축제 채우기 (LLM 호출 없음)
  ```
  권역을 늘리려면 `regions.json`에 항목을 추가하고 `explore`의 `province` 값을 쓰면 됩니다.
- **첫 화면:** `GET /explore?province=경남`이 DB의 진행 중·개최예정 스팟을 AI 없이 바로 돌려줍니다 (서버 시작 시 미리 불러와 캐시, 15분). 줌 단계에 따라 시·도 → 시·군 배지 → 개별 핀으로 바뀝니다.
- **추천 문구:** T1은 경남 군·섬 지역에서 이동 수단이 없으면 자차(반경 30km)로 추정하고, T3는 지역 특색을 분위기 설명에만 쓰고 데이터에 없는 사실은 쓰지 않습니다.
- **사진:** TourAPI가 주는 대표 사진을 카드에 쓰며, 없으면 분류 색 배경으로 대체합니다. 한국관광공사 사진은 카드 상세에 출처를 표시합니다.

## Vercel 배포

이 프로젝트는 설정 파일이 준비돼 있습니다. `app/main.py`의 `app`을 Vercel이 FastAPI로 자동 인식하고, `vercel.json`이 프론트를 빌드한 뒤(`frontend/dist`) CDN으로 올립니다.

1. **코드를 GitHub에 올립니다.** 지금 폴더는 git 저장소가 아니므로 `git init` → `git add .` → `git commit -m "init"` 후 GitHub 저장소를 만들어 push합니다. `.env`는 `.gitignore`에 들어 있어 올라가지 않습니다 (커밋 전에 `git status`에 `.env`가 없는지 꼭 확인하세요).
2. Vercel 대시보드 → **Add New → Project** → 저장소 선택. Framework는 FastAPI로 자동 인식되고, 빌드 명령은 `vercel.json`에서 읽습니다. 아직 **Deploy를 누르지 마세요.**
3. **Environment Variables**에 `.env` 내용을 넣습니다 (`KAKAO_JS_KEY`도 포함. 카카오 앱의 Web 플랫폼에 배포 주소를 등록해야 지도가 뜹니다). 입력란에 `.env` 파일 내용을 통째로 붙여 넣으면 한 번에 등록됩니다. 비어 있는 값은 빼고, `MOIS_FESTIVAL_FILE`(로컬 파일 경로)은 넣지 않습니다.
4. **Deploy**. 배포 뒤 `https://<프로젝트>.vercel.app/` 이 열리고 경남 둘러보기가 나오면 정상입니다.

CLI로 올리려면: `npm i -g vercel` → `vercel login` → 프로젝트 폴더에서 `vercel` (미리보기), `vercel --prod` (운영). `.vercelignore`가 `.env`와 로컬 산출물을 올리지 않게 막습니다.

**배포 전에 알아 둘 점**
- **LLM 비용 보호:** 공개 주소의 `/api/pipeline`, `/api/reroute`, `/api/parse`는 누구나 호출할 수 있어 LLM 비용이 듭니다. 앱에 IP당 10분 20회 제한(`RATE_LIMIT`, 0이면 끔)을 넣었지만 서버리스에서는 인스턴스마다 따로 세는 간이 방어선입니다. **LLM 서비스의 사용 한도를 꼭 설정**하고, 가능하면 Vercel Firewall의 Rate Limit 규칙도 추가하세요.
- **요청 시간:** 추천 한 번이 30~45초라 `vercel.json`에서 함수 최대 시간을 120초로 잡았습니다. 플랜에 따라 허용 상한이 다르므로 배포가 시간 설정 오류로 실패하면 이 값을 낮추세요.
- **수집은 로컬에서:** `scripts/harvest_regions.py`와 `/harvest`는 오래 걸리고 LLM 비용이 드는 작업이라 서버리스에 맞지 않습니다. 수집은 지금처럼 내 PC에서 돌려 같은 Supabase DB를 채우고, 배포 앱은 DB를 읽기만 합니다. 전국문화축제 CSV(`data/`)도 수집할 때만 쓰이므로 배포에 올라가지 않습니다.
- **둘러보기 캐시:** `/api/explore`는 CDN이 15분간 보관합니다. 수집한 새 데이터가 화면에 보이기까지 최대 15분 걸릴 수 있습니다.
- **서버 시작 시 미리 불러오기(warm)는 Vercel에서 꺼집니다.** 서버리스는 인스턴스가 수시로 바뀌기 때문입니다. 대신 위 CDN 캐시가 첫 방문 지연을 줄입니다.
- **Python 3.13**(`.python-version`)과 `requirements.txt`의 실행용 패키지만 번들에 들어갑니다 (테스트·uvicorn은 `requirements-dev.txt`).

## 알려진 한계

- **상영 회차 없음:** KOBIS에는 극장별 시간표가 없습니다. 영화관은 위치와 박스오피스 상영작까지만 제공되고 "회차 미확인"으로 표시됩니다. 회차는 극장별 소스가 필요합니다.
- **미검증 소스:** 네이버 블로그·뉴스 기반 플리마켓/가오픈은 신뢰도 0.4~0.5로 표시되는 미검증 데이터입니다. 글에 정확한 장소(도로명·지번)가 없어 시·군 단위로만 확인되는 항목은 지도에 찍지 않고 버립니다. 날짜가 없는 항목은 수집 후 14일이 지나면 자동으로 검색에서 빠집니다.
- **TourAPI 링크:** 항목의 `source_url`은 공식 상세 페이지가 아닌 지도 검색 링크입니다.
- **전국문화축제표준데이터는 파일 데이터입니다.** API가 아니라서 data.go.kr에서 CSV를 내려받아 `data/festival_standard.csv`(또는 `MOIS_FESTIVAL_FILE`)에 두어야 합니다. 없으면 이 소스만 건너뛰고 TourAPI 축제로 동작합니다. 컬럼명은 한글/영문 별칭을 모두 허용하며, 실제 내려받은 파일로 동작을 확인했습니다.
- **응답 속도:** `/pipeline` 한 번에 30~45초 정도입니다 (T1 약 5초, T2 약 10초, T3 약 15초). T2는 판단만 출력하게 줄였고, 후보는 카테고리별 8개·총 24개로 제한합니다. OpenAI 호환 호출은 추론 강도를 낮추는 `output_config.effort=low`를 보내고(`API_EFFORT`, 서비스가 거부하면 자동 제외), 게이트웨이 504를 피하려고 스트리밍을 씁니다 (`API_STREAM`). 추론 강도를 낮추면 후보를 더 엄격하게 거를 수 있습니다.
- **지도 엔진 선택:** `KAKAO_JS_KEY`가 있으면 **카카오맵**을 쓰고(`KakaoMapView.tsx`), 없거나 불러오지 못하면(키·도메인 설정 오류, 광고 차단 등) 자동으로 아래 OpenFreeMap 지도로 되돌아갑니다. 카카오맵은 앱 설정의 **Web 플랫폼에 접속 주소를 등록**한 곳에서만 뜹니다 (`http://localhost:8000`, 배포 주소 등. `127.0.0.1`은 다른 주소로 취급됩니다). 주소에 `?map=leaflet`을 붙이면 OpenFreeMap을 강제로 볼 수 있습니다. 카카오 JavaScript 키는 브라우저에 공개되는 키라서 `/api/config`로 이 키 하나만 화면에 전달합니다. 카카오맵을 쓸 때는 카카오 로고와 출처 표기를 지우지 마세요.
- **OpenFreeMap 지도:** Leaflet 위에 OpenFreeMap 벡터 지도(MapLibre)를 얹었습니다. 키·가입이 필요 없고 지명은 한글 우선으로 표시합니다. 스타일은 `frontend/src/mapStyle.ts`의 `DEFAULT_TILE`(positron/liberty/bright)에서 고르고, 주소에 `?tiles=liberty`를 붙여 미리 비교할 수 있습니다. WebGL을 못 쓰는 기기에서는 OSM 타일로 자동 대체됩니다. OpenFreeMap·OpenStreetMap 출처 표기는 지도와 패널 아래에 두었으니 지우지 마세요. 카카오/네이버 지도로 바꾸려면 `MapView.tsx`와 `basemap.ts`를 교체하면 됩니다. (CARTO 기본 지도는 이제 API 키가 필요해 쓰지 않습니다.)
- **현재 위치 기반 재검색 없음:** T5 후보는 최초 T2 결과 안에서만 고릅니다.

## 테스트

```powershell
.venv\Scripts\python -m pytest -q          # 백엔드 (외부 호출은 모두 모의)
cd frontend; npm test; npm run build        # 프론트 단위 테스트 + 타입 검사
```
