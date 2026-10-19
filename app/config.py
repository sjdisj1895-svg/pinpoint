"""환경변수 설정. 키는 로그/예외에 노출하지 않는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import unquote


@dataclass(frozen=True)
class Settings:
    data_go_key: str = ""  # 공공데이터포털(TourAPI·전국문화축제표준데이터) 서비스키 (Decoding 키)
    tourapi_version: str = "2"  # KorService 버전 (현행 2, 구버전 1)
    # 전국문화축제표준데이터 CSV (data.go.kr 파일 데이터). 프로젝트 루트 기준 상대경로 허용
    mois_festival_file: str = "data/festival_standard.csv"
    kobis_key: str = ""
    kakao_rest_key: str = ""
    kakao_js_key: str = ""  # 카카오맵 JavaScript 키 (브라우저에 공개되는 키. 등록한 도메인에서만 동작)
    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_api_mode: str = "hub"  # hub(네이버 클라우드 API Hub) | developers(네이버 개발자센터)
    supabase_url: str = ""
    supabase_service_key: str = ""
    admin_token: str = ""

    @property
    def has_store(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def has_any_connector(self) -> bool:
        return bool(self.data_go_key or self.kobis_key or self.kakao_rest_key or self.naver_client_id)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env
    return Settings(
        # 포털에서 복사한 Encoding 키(%2B 등 포함)를 넣어도 httpx가 다시 인코딩하지 않도록 디코딩
        data_go_key=unquote(e.get("DATA_GO_KR_KEY", "")),
        tourapi_version=e.get("TOURAPI_VERSION", "2"),
        mois_festival_file=e.get("MOIS_FESTIVAL_FILE") or "data/festival_standard.csv",
        kobis_key=e.get("KOBIS_KEY", ""),
        kakao_rest_key=e.get("KAKAO_REST_KEY", ""),
        kakao_js_key=e.get("KAKAO_JS_KEY", "").strip(),
        naver_client_id=e.get("NAVER_CLIENT_ID", ""),
        naver_client_secret=e.get("NAVER_CLIENT_SECRET", ""),
        naver_api_mode=(e.get("NAVER_API_MODE") or "hub").strip().lower(),
        supabase_url=e.get("SUPABASE_URL", ""),
        supabase_service_key=e.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        admin_token=e.get("ADMIN_TOKEN", ""),
    )
