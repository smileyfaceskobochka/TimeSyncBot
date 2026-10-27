"""
TimeSyncBot internal REST API (bot client <-> server).
Guarded by the X-API-Key header (verify_internal_key dependency).
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from server.api.dependencies import get_db, verify_internal_key
from server.database.repositories import (
    AnalyticsRepository,
    GroupChatRepository,
    OccupancyRepository,
    ScheduleRepository,
    UserRepository,
)
from server.services.parser.teacher_parser import teacher_mapping_manager
from core.models import GroupChat, User

router = APIRouter(
    tags=["Internal"],
    dependencies=[Depends(verify_internal_key)],
)


# ================= USERS =================
@router.get("/users/with-group")
async def get_all_users_with_group_internal(db=Depends(get_db)):
    repo: UserRepository = UserRepository(db)
    users = await repo.get_all_users_with_group()
    return [u.model_dump(mode="json") for u in users]


@router.get("/users/by-group/{group_name}")
async def get_users_by_group_internal(group_name: str, db=Depends(get_db)):
    repo: UserRepository = UserRepository(db)
    return await repo.get_users_by_group(group_name)


@router.get("/users/{telegram_id}")
async def get_user_internal(telegram_id: int, db=Depends(get_db)):
    repo: UserRepository = UserRepository(db)
    user = await repo.get_user(telegram_id)
    if user is None:
        return None
    return user.model_dump(mode="json")


@router.post("/users/{telegram_id}")
async def upsert_user_internal(telegram_id: int, user_body: User, db=Depends(get_db)):
    repo: UserRepository = UserRepository(db)
    payload = user_body.model_dump(mode="json") if hasattr(user_body, "model_dump") else dict(user_body)
    payload["telegram_id"] = telegram_id
    user = User(**payload)
    await repo.upsert_user(user)
    return {"ok": True}


@router.post("/users/{telegram_id}/settings/{field}")
async def update_user_setting_internal(telegram_id: int, field: str, value: bool, db=Depends(get_db)):
    repo: UserRepository = UserRepository(db)
    await repo.update_user_setting(telegram_id, field, value)
    return {"ok": True}


@router.get("/bot-settings")
async def get_bot_settings_internal(db=Depends(get_db)):
    repo: UserRepository = UserRepository(db)
    return await repo.get_settings()


@router.post("/bot-settings/{key}")
async def update_bot_setting_internal(key: str, body: dict, db=Depends(get_db)):
    repo: UserRepository = UserRepository(db)
    await repo.update_setting(key, str(body.get("value") or ""))
    return {"ok": True}


# ================= SCHEDULE =================
@router.get("/schedule/day")
async def get_schedule_day_internal(group: str = Query(...), date_str: str = Query(..., alias="date"), db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    lessons, is_predicted = await repo.get_lessons_with_status(group, date.fromisoformat(date_str))
    return {
        "lessons": [l.model_dump(mode="json") for l in lessons],
        "is_predicted": is_predicted,
    }


@router.get("/schedule/groups")
async def get_lessons_for_groups_internal(groups: str = Query(...), date_str: str = Query(..., alias="date"), db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    group_list = [g for g in groups.split(",") if g]
    lessons = await repo.get_lessons_for_groups(group_list, date.fromisoformat(date_str))
    return [l.model_dump(mode="json") for l in lessons]


@router.get("/schedule/groups/all")
async def get_all_group_names_internal(db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return await repo.get_all_group_names()


@router.get("/schedule/groups/{group_name}/has-lessons")
async def has_lessons_for_group_internal(group_name: str, db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return bool(await repo.has_lessons_for_group(group_name))


@router.get("/schedule/search/groups")
async def search_groups_internal(q: str = Query(..., alias="q"), db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return await repo.search_groups(q)


@router.get("/schedule/search/tracked-groups")
async def search_tracked_groups_internal(q: str = Query(..., alias="q"), db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return await repo.search_tracked_groups(q)


@router.get("/schedule/search/teachers")
async def search_teachers_internal(q: str = Query(..., alias="q"), db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return await repo.search_teachers(q)


@router.get("/schedule/tracked-groups/count")
async def get_tracked_groups_count_internal(db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return int(await repo.get_tracked_groups_count())


@router.post("/schedule/tracked-groups/{group_name}")
async def set_group_tracked_internal(group_name: str, body: dict, db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    await repo.set_group_tracked(group_name, bool(body.get("is_tracked", True)))
    return {"ok": True}


@router.get("/schedule/resolve-group")
async def resolve_group_internal(q: str = Query(..., alias="q"), db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return await repo.resolve_canonical_group_name(q)


# ================= TEACHERS =================
@router.get("/teachers/search")
async def search_teachers_internal(q: str = Query(..., alias="q"), db=Depends(get_db)):
    await teacher_mapping_manager.ensure_mapping()
    return teacher_mapping_manager.search_teachers(q)


@router.get("/teachers/{teacher_name}/schedule")
async def get_teacher_schedule_internal(teacher_name: str, date_str: str = Query(..., alias="date"), db=Depends(get_db)):
    await teacher_mapping_manager.ensure_mapping()
    current_date = date.fromisoformat(date_str)
    lessons = await teacher_mapping_manager.fetch_teacher_lessons(teacher_name, current_date)
    rep = teacher_mapping_manager.get_teacher_report_for_date(teacher_name, current_date)
    departments = teacher_mapping_manager.get_teacher_departments(teacher_name) or [
        teacher_mapping_manager.get_teacher_department(teacher_name)
    ]
    return {
        "lessons": lessons,
        "report": rep,
        "departments": departments,
    }


@router.get("/teachers/{teacher_name}/departments")
async def get_teacher_departments_internal(teacher_name: str, db=Depends(get_db)):
    await teacher_mapping_manager.ensure_mapping()
    departments = teacher_mapping_manager.get_teacher_departments(teacher_name) or [
        teacher_mapping_manager.get_teacher_department(teacher_name)
    ]
    return {"departments": departments}


@router.get("/teachers/{teacher_name}/report")
async def get_teacher_report_internal(teacher_name: str, date_str: str = Query(..., alias="date"), db=Depends(get_db)):
    await teacher_mapping_manager.ensure_mapping()
    return teacher_mapping_manager.get_teacher_report_for_date(teacher_name, date.fromisoformat(date_str))


@router.get("/teachers/{teacher_name}/curriculum")
async def get_teacher_curriculum_internal(teacher_name: str, db=Depends(get_db)):
    await teacher_mapping_manager.ensure_mapping()
    return teacher_mapping_manager.get_teacher_curriculum(teacher_name)


@router.get("/teachers/{teacher_name}/lessons")
async def get_teacher_lessons_internal(teacher_name: str, date_str: str = Query(..., alias="date"), db=Depends(get_db)):
    repo: ScheduleRepository = ScheduleRepository(db)
    return [l.model_dump(mode="json") for l in await repo.get_lessons_for_teacher(teacher_name, date.fromisoformat(date_str))]


# ================= OCCUPANCY =================
@router.get("/occupancy/buildings")
async def get_buildings_internal(db=Depends(get_db)):
    repo: OccupancyRepository = OccupancyRepository(db)
    return await repo.get_buildings()


@router.get("/occupancy/rooms")
async def get_rooms_internal(building: Optional[str] = None, db=Depends(get_db)):
    repo: OccupancyRepository = OccupancyRepository(db)
    return list(repo.get_all_rooms(building))


@router.get("/occupancy/occupied")
async def get_occupied_internal(date_str: str, pair: int, building: Optional[str] = None, db=Depends(get_db)):
    repo: OccupancyRepository = OccupancyRepository(db)
    return list(await repo.get_occupied_rooms(date.fromisoformat(date_str), pair, building))


@router.get("/occupancy/pairs")
async def get_pairs_internal(date_str: str, building: str, db=Depends(get_db)):
    repo: OccupancyRepository = OccupancyRepository(db)
    return list(await repo.get_available_pairs(date.fromisoformat(date_str), building))


# ================= ANALYTICS =================
@router.post("/analytics/log")
async def log_action_internal(body: dict, db=Depends(get_db)):
    repo: AnalyticsRepository = AnalyticsRepository(db)
    await repo.log_action(int(body.get("user_id") or 0), str(body.get("action") or ""), body.get("details"))
    return {"ok": True}


# ================= GROUP CHATS =================
@router.get("/group-chats/for-time")
async def get_chats_for_time_internal(time: str = Query(..., alias="time"), db=Depends(get_db)):
    repo: GroupChatRepository = GroupChatRepository(db)
    return [c.model_dump(mode="json") for c in await repo.get_chats_for_time(time)]


@router.get("/group-chats/active")
async def get_all_active_chats_internal(db=Depends(get_db)):
    repo: GroupChatRepository = GroupChatRepository(db)
    return [c.model_dump(mode="json") for c in await repo.get_all_active_chats()]


@router.get("/group-chats/{chat_id}")
async def get_chat_internal(chat_id: int, db=Depends(get_db)):
    repo: GroupChatRepository = GroupChatRepository(db)
    chat = await repo.get_chat(chat_id)
    if not chat:
        return None
    return chat.model_dump(mode="json")


@router.post("/group-chats/{chat_id}")
async def upsert_chat_internal(chat_id: int, chat_body: dict, db=Depends(get_db)):
    repo: GroupChatRepository = GroupChatRepository(db)
    chat = GroupChat(**{**chat_body, "chat_id": chat_id})
    await repo.upsert_chat(chat)
    return {"ok": True}


@router.delete("/group-chats/{chat_id}")
async def delete_chat_internal(chat_id: int, db=Depends(get_db)):
    repo: GroupChatRepository = GroupChatRepository(db)
    await repo.delete_chat(chat_id)
    return {"ok": True}


# ================= PARSER =================
@router.get("/parser/status")
async def get_parser_status_internal():
    return {"running": False, "last_run": None, "last_status": "never", "stats": {"total_runs": 0, "successful_runs": 0, "failed_runs": 0}}


@router.post("/parser/run")
async def run_parser_internal(db=Depends(get_db)):
    from server.scheduler import parser_scheduler
    await parser_scheduler.run_parser_process()
    return {"ok": True}


@router.post("/parser/run-groups")
async def run_groups_internal(payload: dict, db=Depends(get_db)):
    """On-demand parse for specific groups (keywords) requested by a bot client."""
    groups = payload.get("groups") or []
    if not isinstance(groups, list) or not groups:
        return {"ok": False, "error": "no groups provided"}
    from server.services.parser.runner import run_pipeline
    await run_pipeline(group_keywords=[str(g) for g in groups])
    return {"ok": True}


@router.post("/parser/sync-groups")
async def sync_groups_internal(db=Depends(get_db)):
    from server.services.parser.site_to_pdf import sync_groups_list
    ok = await sync_groups_list(db_manager=db.engine)
    return {"ok": bool(ok)}


@router.get("/parser/logs")
async def get_parser_logs_internal(tail: int = 20, db=Depends(get_db)):
    from pathlib import Path
    from core.config import config
    log_path = Path(config.LOG_DIR) / "bot.log"
    if not log_path.exists():
        return ""
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    last = lines[-tail:] if lines else []
    return "".join(last)
