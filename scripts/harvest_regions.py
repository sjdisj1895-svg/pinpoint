"""정기 수집 배치: 지역 목록을 커넥터로 수집해 Supabase에 upsert한다.

사용 (프로젝트 루트에서):
    python -m scripts.harvest_regions                    # 전체 지역, 오늘/+7일/+14일 기준
    python -m scripts.harvest_regions --only 춘천시 제주시 --offsets 0 --radius 15
스케줄: Windows 작업 스케줄러 또는 cron(예: 매일 04:30)에 위 명령을 등록한다.
외부 API 쿼터와 LLM(Connector D) 비용이 지역 수 × 기준일 수에 비례하므로 지역·기준일을 필요한 만큼만 둔다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

from app.config import load_settings  # noqa: E402
from app.db import SpotStore  # noqa: E402
from app.harvest import Harvester  # noqa: E402
from app.schemas import Category  # noqa: E402

from app.explore import REGIONS  # noqa: E402  (수집 대상 지역 목록. 둘러보기와 같은 파일을 쓴다)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="지정한 region_name만 수집")
    ap.add_argument("--province", help="지정한 권역만 수집 (예: 경남)")
    ap.add_argument("--festival-only", action="store_true",
                    help="모든 기준일에 축제만 수집 (개최예정 행사를 채울 때. 네이버·LLM 호출 없음)")
    ap.add_argument("--offsets", default="0,7,14", help="오늘 기준 +N일 (쉼표 구분)")
    ap.add_argument("--radius", type=float, default=20, help="수집 반경 km (카카오/TourAPI 최대 20)")
    args = ap.parse_args(argv)

    settings = load_settings()
    if not settings.has_store:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY가 필요합니다.", file=sys.stderr)
        return 2
    store = SpotStore.from_settings(settings)
    harvester = Harvester(settings, httpx.Client())

    regions = json.loads(REGIONS.read_text(encoding="utf-8"))
    if args.only:
        regions = [r for r in regions if r["region_name"] in args.only]
    if args.province:
        regions = [r for r in regions if r.get("province") == args.province]
    offsets = [int(x) for x in args.offsets.split(",")]

    failed = 0
    for r in regions:
        for i, off in enumerate(offsets):
            target = date.today() + timedelta(days=off)
            # 관광지·영화관·네이버 결과는 기준일과 무관하므로 첫 기준일에만 수집하고, 이후에는 축제만 수집한다
            cats = set(Category) if i == 0 and not args.festival_only else {Category.FESTIVAL}
            try:
                res = harvester.harvest(lat=r["lat"], lng=r["lng"], radius_km=args.radius, target=target,
                                        region_name=r["region_name"], categories=cats)
                n = store.upsert(res.spots)
            except Exception as e:  # noqa: BLE001  한 지역의 실패가 전체 배치를 멈추지 않게 한다
                failed += 1
                print(f"{r['region_name']} {target} 실패: {type(e).__name__}: {str(e)[:200]}", flush=True)
                continue
            failed += bool(res.errors)
            print(f"{r['region_name']} {target} collected={len(res.spots)} upserted={n} "
                  f"counts={res.counts} errors={res.errors or '-'} skipped={list(res.skipped) or '-'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
