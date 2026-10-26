"""
TimeSyncBot client-side gateway.

Implements the repository interfaces (UserRepository, ScheduleRepository,
OccupancyRepository, AnalyticsRepository, GroupChatRepository, TeacherGateway)
over HTTP against the TimeSyncBot server (core service) REST API
(/api/v1/...). The bot client no longer touches SQLite — the server owns the DB.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional, Set, Tuple

import httpx

from core.config import config
from core.models import GroupChat, Lesson, User


class ServerUnavailable(RuntimeError):
    pass


class ServerGateway:
    """Holds the shared httpx client used by all gateway instances."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        # All gateway paths are relative to the API v1 root (e.g. "/internal/users/...").
        base = (base_url or config.SERVER_URL).rstrip("/")
        self.base_url = base if base.endswith("/api/v1") else f"{base}/api/v1"
        self.api_key = api_key or config.BOT_API_KEY
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key} if self.api_key else {},
            timeout=httpx.Timeout(connect=10.0, read=900.0, write=60.0, pool=10.0),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        try:
            resp = await self.client.request(method, path, params=params, json=json_body, timeout=timeout)
        except httpx.HTTPError as e:
            raise ServerUnavailable(f"TimeSync server is unreachable: {e}") from e
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return None


class UserRepository(ServerGateway):
    async def create_tables(self):
        return None

    async def get_user(self, telegram_id: int) -> Optional[User]:
        data = await self._request("GET", f"/internal/users/{telegram_id}")
        if data is None:
            return None
        return User.model_validate(data)

    async def upsert_user(self, user: User) -> None:
        data = user.model_dump(mode="json")
        data["telegram_id"] = user.telegram_id
        await self._request("POST", f"/internal/users/{user.telegram_id}", json_body=data)

    async def get_users_by_group(self, group_name: str) -> List[User]:
        users = await self._request("GET", "/internal/users/by-group", params={"group": group_name})
        if not users:
            return []
        return [User.model_validate(u) for u in users]

    async def get_all_users_with_group(self) -> List[User]:
        users = await self._request("GET", "/internal/users/with-group")
        if not users:
            return []
        return [User.model_validate(u) for u in users]

    async def get_settings(self) -> dict:
        return await self._request("GET", "/internal/bot-settings") or {}

    async def update_setting(self, key: str, value: str) -> None:
        await self._request("POST", f"/internal/bot-settings/{key}", json_body={"value": value})


class TeacherGateway(ServerGateway):
    async def search(self, query: str) -> List[str]:
        result = await self._request("GET", "/internal/teachers/search", params={"q": query})
        return list(result or [])

    async def get_lessons(self, teacher_name: str, target_date: Optional[date] = None) -> List[dict]:
        params: dict = {}
        if target_date is not None:
            params["date"] = target_date.isoformat()
        result = await self._request("GET", f"/internal/teachers/{teacher_name}/schedule", params=params)
        return list(result or {}).get("lessons") or []

    async def get_departments(self, teacher_name: str) -> List[str]:
        result = await self._request("GET", f"/internal/teachers/{teacher_name}/departments")
        return list(result or {}).get("departments") or []

    async def get_department(self, teacher_name: str) -> Optional[str]:
        departments = await self.get_departments(teacher_name)
        return departments[0] if departments else None

    async def get_report(self, teacher_name: str, target_date: Optional[date] = None) -> Optional[dict]:
        params: dict = {}
        if target_date is not None:
            params["date"] = target_date.isoformat()
        return await self._request("GET", f"/internal/teachers/{teacher_name}/report", params=params)

    async def get_curriculum(self, teacher_name: str) -> List[dict]:
        return list(await self._request("GET", f"/internal/teachers/{teacher_name}/curriculum") or [])


class ScheduleRepository(ServerGateway):
    async def get_lessons_for_groups(self, group_names: List[str], target_date: date) -> List[Lesson]:
        if not group_names:
            return []
        result = await self._request("GET", "/internal/schedule/groups", params={"groups": ",".join(group_names), "date": target_date.isoformat()})
        if not result:
            return []
        return [Lesson.model_validate(l) for l in result]

    async def get_all_group_names(self) -> List[str]:
        return list(await self._request("GET", "/internal/schedule/groups/all") or [])

    async def search_groups(self, query: str) -> List[str]:
        return list(await self._request("GET", "/internal/schedule/search/groups", params={"q": query}) or [])

    async def search_tracked_groups(self, query: str) -> List[str]:
        return list(await self._request("GET", "/internal/schedule/search/tracked-groups", params={"q": query}) or [])

    async def search_teachers(self, query: str) -> List[str]:
        return list(await self._request("GET", "/internal/schedule/search/teachers", params={"q": query}) or [])

    async def get_lessons_for_teacher(self, teacher_name: str, target_date: Optional[date] = None) -> List[Lesson]:
        result = await self._request("GET", f"/internal/teachers/{teacher_name}/lessons", params={"date": (target_date or date.today()).isoformat()})
        if not result:
            return []
        return [Lesson.model_validate(l) for l in result]

    async def get_tracked_groups_count(self) -> int:
        result = await self._request("GET", "/internal/schedule/tracked-groups/count")
        return int(result or 0)

    async def set_group_tracked(self, group_name: str, is_tracked: bool = True) -> None:
        await self._request("POST", f"/internal/schedule/tracked-groups/{group_name.replace('/', '%2F')}", json_body={"is_tracked": is_tracked})

    async def has_lessons_for_group(self, group_name: str) -> bool:
        result = await self._request("GET", f"/internal/schedule/groups/{group_name}/has-lessons")
        return bool(result)

    async def resolve_canonical_group_name(self, query: str) -> str:
        result = await self._request("GET", "/internal/schedule/resolve-group", params={"q": query})
        return result or query

    async def get_lessons_with_status(self, group_name: str, target_date: date) -> Tuple[List[Lesson], bool]:
        result = await self._request("GET", "/internal/schedule/day", params={"group": group_name, "date": target_date.isoformat()})
        if not result:
            return [], False
        lessons = [Lesson.model_validate(l) for l in result.get("lessons") or []]
        return lessons, bool(result.get("is_predicted"))


class OccupancyRepository(ServerGateway):
    async def get_buildings(self) -> List[str]:
        return list(await self._request("GET", "/internal/occupancy/buildings") or [])

    async def get_all_rooms(self, building: Optional[str] = None) -> Set[str]:
        result = await self._request("GET", "/internal/occupancy/rooms", params={"building": building} if building else None)
        return set(result or [])

    async def get_occupied_rooms(self, target_date: date, pair_number: int, building: Optional[str] = None) -> Set[str]:
        params: dict = {"date": target_date.isoformat(), "pair": str(pair_number)}
        if building:
            params["building"] = building
        result = await self._request("GET", "/internal/occupancy/occupied", params=params)
        return set(result or [])

    async def get_available_pairs(self, target_date: date, building: str) -> List[int]:
        result = await self._request("GET", "/internal/occupancy/pairs", params={"date": target_date.isoformat(), "building": building})
        return list(result or [])


class AnalyticsRepository(ServerGateway):
    async def create_tables(self):
        return None

    async def log_action(self, user_id: int, action: str, details: Optional[str] = None) -> None:
        await self._request("POST", "/internal/analytics/log", json_body={"user_id": user_id, "action": action, "details": details})


class GroupChatRepository(ServerGateway):
    async def create_tables(self):
        return None

    async def get_chat(self, chat_id: int) -> Optional[GroupChat]:
        data = await self._request("GET", f"/internal/group-chats/{chat_id}")
        if not data:
            return None
        return GroupChat.model_validate(data)

    async def upsert_chat(self, chat: GroupChat) -> None:
        body = chat.model_dump(mode="json")
        body["chat_id"] = chat.chat_id
        body["topic_id"] = chat.topic_id
        await self._request("POST", f"/internal/group-chats/{chat.chat_id}", json_body=body)

    async def get_chats_for_time(self, current_time: str) -> List[GroupChat]:
        chats = await self._request("GET", "/internal/group-chats/for-time", params={"time": current_time})
        if not chats:
            return []
        return [GroupChat.model_validate(c) for c in chats]

    async def get_all_active_chats(self) -> List[GroupChat]:
        chats = await self._request("GET", "/internal/group-chats/active")
        if not chats:
            return []
        return [GroupChat.model_validate(c) for c in chats]

    async def delete_chat(self, chat_id: int) -> None:
        await self._request("DELETE", f"/internal/group-chats/{chat_id}")


class ParserServerProxy(ServerGateway):
    """Proxy surface used by the bot admin commands + notification scheduler."""

    async def run_parser_process(self) -> dict:
        status = await self._request("POST", "/internal/parser/run")
        if status is None:
            return {"last_status": "failed"}
        return status

    async def run_now(self) -> dict:
        return await self.run_parser_process()

    async def get_status(self) -> dict:
        status = await self._request("GET", "/internal/parser/status") or {}
        last_run = status.get("last_run")
        if isinstance(last_run, str):
            status["last_run"] = datetime.fromisoformat(last_run)
        stats = status.get("stats") or {}
        return {
            "running": False,
            "last_run": status.get("last_run"),
            "last_status": status.get("last_status") or "never",
            "stats": {
                "total_runs": int(stats.get("total_runs") or 0),
                "successful_runs": int(stats.get("successful_runs") or 0),
                "failed_runs": int(stats.get("failed_runs") or 0),
            },
        }

    async def sync_groups(self) -> bool:
        return bool(await self._request("POST", "/internal/parser/sync-groups"))

    async def run_groups(self, groups: list) -> bool:
        return bool(await self._request("POST", "/internal/parser/run-groups", json_body={"groups": list(groups)}))

    async def sync_teachers(self) -> bool:
        return bool(await self._request("POST", "/internal/parser/sync-teachers"))

    async def sync_occupancy(self) -> bool:
        return bool(await self._request("POST", "/internal/parser/sync-occupancy"))

    async def get_parser_logs(self, tail: int = 20) -> str:
        return (await self._request("GET", "/internal/parser/logs", params={"tail": str(tail)})) or ""


class ParserSchedulerService(ParserServerProxy):
    """Notification scheduler facade — also proxies parser control to the server."""

    def __init__(
        self,
        db_manager=None,
        schedule_repo: Optional[ScheduleRepository] = None,
        analytics_repo=None,
        group_chat_repo: Optional[GroupChatRepository] = None,
        user_repo: Optional[UserRepository] = None,
        bot=None,
        run_on_startup: bool = False,
    ):
        super().__init__()
        self.schedule_repo = schedule_repo
        self.group_chat_repo = group_chat_repo
        self.user_repo = user_repo
        self.bot = bot
        self.run_on_startup = run_on_startup
        self._sent_lesson_alerts: set = set()

    async def run_parser_process(self):
        return await ParserServerProxy.run_parser_process(self)

    async def run_now(self):
        return await ParserServerProxy.run_now(self)

    async def get_status(self):
        return await ParserServerProxy.get_status(self)
