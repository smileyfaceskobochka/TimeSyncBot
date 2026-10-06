"""
REST API server for Android widget sync.
Runs concurrently with the Telegram bot using aiohttp.

Endpoints:
    GET /api/health             — Health check
    GET /api/groups/search?q=  — Search university groups
    GET /api/schedule/{group}  — Get schedule for the current week (upcoming 7 days)
"""
import logging
from datetime import date, timedelta

from aiohttp import web
from tgbot.database.repositories import DatabaseManager, ScheduleRepository

_db_manager: DatabaseManager | None = None


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "timestamp": date.today().isoformat()})


async def handle_groups_search(request: web.Request) -> web.Response:
    query = request.rel_url.query.get("q", "").strip()
    if not query:
        return web.json_response({"error": "Missing 'q' query parameter"}, status=400)

    repo = ScheduleRepository(_db_manager)
    results = await repo.search_tracked_groups(query)
    return web.json_response({"results": results, "count": len(results)})


async def handle_get_schedule(request: web.Request) -> web.Response:
    group_name = request.match_info.get("group_name", "").strip()
    if not group_name:
        return web.json_response({"error": "Missing group_name"}, status=400)

    # Accept optional ?date=YYYY-MM-DD or default to today
    date_str = request.rel_url.query.get("date", date.today().isoformat())
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        return web.json_response({"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}, status=400)

    repo = ScheduleRepository(_db_manager)
    schedule_days = []

    # Return 7 days of schedule starting from the requested date
    for offset in range(7):
        day = target + timedelta(days=offset)
        lessons, predicted = await repo.get_lessons_with_status(group_name, day)

        schedule_days.append({
            "date": day.isoformat(),
            "predicted": predicted,
            "lessons": [
                {
                    "pair_number": l.pair_number,
                    "start_time": l.start_time,
                    "end_time": l.end_time,
                    "subject": l.subject,
                    "class_type": l.class_type,
                    "teacher": l.teacher,
                    "building": l.building,
                    "room": l.room,
                    "subgroup": l.subgroup,
                }
                for l in lessons
            ],
        })

    return web.json_response({"group": group_name, "start_date": date_str, "schedule": schedule_days})


async def handle_teachers_search(request: web.Request) -> web.Response:
    query = request.rel_url.query.get("q", "").strip()
    if not query:
        return web.json_response({"error": "Missing 'q' query parameter"}, status=400)

    from tgbot.services.parser.teacher_parser import teacher_mapping_manager
    if not teacher_mapping_manager.is_mapped():
        await teacher_mapping_manager.ensure_mapping()
    results = teacher_mapping_manager.search_teachers(query)
    return web.json_response({"results": results, "count": len(results)})


async def handle_get_teacher_curriculum(request: web.Request) -> web.Response:
    teacher_name = request.match_info.get("teacher_name", "").strip()
    if not teacher_name:
        return web.json_response({"error": "Missing teacher_name"}, status=400)

    from tgbot.services.parser.teacher_parser import teacher_mapping_manager
    if not teacher_mapping_manager.is_mapped():
        await teacher_mapping_manager.ensure_mapping()

    dept = teacher_mapping_manager.get_teacher_department(teacher_name)
    curriculum = teacher_mapping_manager.get_teacher_curriculum(teacher_name)
    return web.json_response({
        "teacher": teacher_name,
        "department": dept,
        "curriculum": curriculum,
        "count": len(curriculum)
    })


def setup_app(db: DatabaseManager) -> web.Application:
    global _db_manager
    _db_manager = db

    app = web.Application()
    app.add_routes([
        web.get("/api/health", handle_health),
        web.get("/api/groups/search", handle_groups_search),
        web.get("/api/schedule/{group_name}", handle_get_schedule),
        web.get("/api/teachers/search", handle_teachers_search),
        web.get("/api/teachers/{teacher_name}/curriculum", handle_get_teacher_curriculum),
    ])
    logging.info("✅ API routes registered: /api/health, /api/groups/search, /api/schedule/{group_name}, /api/teachers/search, /api/teachers/{teacher_name}/curriculum")
    return app
