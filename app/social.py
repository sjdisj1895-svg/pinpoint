"""좋아요·댓글 저장소 (Supabase). 모든 접근은 서버의 service_role 키로만 한다."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

MAX_COMMENT = 300
REPORT_HIDE_THRESHOLD = 3  # 신고가 이 수 이상이면 자동으로 숨긴다
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # 줄바꿈(\n)은 남기고 나머지 제어 문자는 제거
_BLANKS = re.compile(r"\n{3,}")


def clean_comment(raw: str) -> str:
    """제어 문자를 지우고 앞뒤 공백을 다듬고 과도한 빈 줄을 줄인다. (HTML은 화면이 텍스트로만 그리므로 따로 막지 않는다)"""
    return _BLANKS.sub("\n\n", _CTRL.sub("", raw).replace("\r\n", "\n").replace("\r", "\n")).strip()


class SocialStore:
    def __init__(self, client: Any):
        self.client = client

    # ---- 사용자 ----
    def upsert_user(self, kakao_id: int, nickname: str) -> None:
        self.client.table("users").upsert(
            {"kakao_id": kakao_id, "nickname": nickname, "last_login": datetime.now(timezone.utc).isoformat()},
            on_conflict="kakao_id",
        ).execute()

    # ---- 장소 ----
    def place_exists(self, place_id: str) -> bool:
        """존재하지 않는 장소에 좋아요·댓글이 쌓이지 않게 한다."""
        res = self.client.table("spots").select("id").eq("id", place_id).limit(1).execute()
        return bool(res.data)

    # ---- 좋아요 ----
    def toggle_like(self, place_id: str, user_id: int) -> dict[str, Any]:
        row = self.client.rpc("toggle_like", {"p_place": place_id, "p_user": user_id}).execute().data[0]
        return {"liked": bool(row["out_liked"]), "likes": int(row["out_likes"])}

    def summary(self, place_ids: list[str], user_id: int | None) -> dict[str, dict[str, Any]]:
        if not place_ids:
            return {}
        rows = self.client.rpc("place_social", {"p_ids": place_ids, "p_user": user_id}).execute().data or []
        return {
            str(r["out_place"]): {"likes": int(r["out_likes"]), "comments": int(r["out_comments"]), "liked": bool(r["out_liked"])}
            for r in rows
        }

    # ---- 댓글 ----
    @staticmethod
    def _comment(row: dict[str, Any], me: int | None) -> dict[str, Any]:
        user = row.get("users") or {}
        return {
            "id": row["id"], "body": row["body"], "created_at": row["created_at"],
            "nickname": user.get("nickname") or "카카오 사용자", "mine": me is not None and row["user_id"] == me,
        }

    def list_comments(self, place_id: str, me: int | None, limit: int = 20, before: str | None = None) -> list[dict[str, Any]]:
        q = (
            self.client.table("comments").select("id, body, created_at, user_id, users!comments_user_id_fkey(nickname)")
            .eq("place_id", place_id).eq("hidden", False).order("created_at", desc=True).limit(limit)
        )
        if before:
            q = q.lt("created_at", before)
        return [self._comment(r, me) for r in (q.execute().data or [])]

    def add_comment(self, place_id: str, user_id: int, body: str) -> dict[str, Any]:
        row = self.client.table("comments").insert({"place_id": place_id, "user_id": user_id, "body": body}).execute().data[0]
        full = (
            self.client.table("comments").select("id, body, created_at, user_id, users!comments_user_id_fkey(nickname)").eq("id", row["id"]).execute().data[0]
        )
        return self._comment(full, user_id)

    def delete_comment(self, comment_id: str, user_id: int) -> bool:
        """본인 댓글만 지운다. 지워졌으면 True."""
        res = self.client.table("comments").delete().eq("id", comment_id).eq("user_id", user_id).execute()
        return bool(res.data)

    def report_comment(self, comment_id: str, user_id: int) -> dict[str, bool]:
        row = self.client.rpc(
            "report_comment", {"p_comment": comment_id, "p_user": user_id, "p_threshold": REPORT_HIDE_THRESHOLD}
        ).execute().data[0]
        return {"reported": bool(row["out_reported"]), "hidden": bool(row["out_hidden"])}

    def comment_author(self, comment_id: str) -> int | None:
        res = self.client.table("comments").select("user_id").eq("id", comment_id).limit(1).execute()
        return res.data[0]["user_id"] if res.data else None

    # ---- 관리자 ----
    def admin_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        res = (
            self.client.table("comments").select("id, place_id, body, reports, hidden, created_at, user_id, users!comments_user_id_fkey(nickname)")
            .gt("reports", 0).order("reports", desc=True).limit(limit).execute()
        )
        return res.data or []

    def admin_delete(self, comment_id: str) -> bool:
        return bool(self.client.table("comments").delete().eq("id", comment_id).execute().data)
