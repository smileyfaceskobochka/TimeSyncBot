import json
import logging
import asyncio
from datetime import date
from typing import Optional, List, Set, Union, Any

from sqlalchemy import select, delete, update, func, or_, text, create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlmodel import SQLModel, select as sqlmodel_select

from tgbot.database.models import User, Lesson, TrackedGroup, ProcessedFile, BotSetting, UserSettings, Occupancy, ActionLog


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Use synchronous engine to avoid greenlet dependency on Python 3.14
        from sqlalchemy import event
        self.engine = create_engine(f"sqlite:///{db_path}")
        
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
            
        self.session_factory = sessionmaker(
            self.engine, expire_on_commit=False, class_=Session
        )

    def create_db_and_tables(self):
        SQLModel.metadata.create_all(self.engine)
        # Migration: ensure all columns exist in occupancy table
        with self.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(occupancy)"))
            columns = [row[1] for row in result.fetchall()]
            
            if "is_free" not in columns:
                logging.info("Migrating: Adding is_free column to occupancy table")
                conn.execute(text("ALTER TABLE occupancy ADD COLUMN is_free BOOLEAN DEFAULT 1"))
            
            if "group_name" not in columns:
                logging.info("Migrating: Adding group_name column to occupancy table")
                conn.execute(text("ALTER TABLE occupancy ADD COLUMN group_name VARCHAR"))
            
            conn.commit()

    def get_session(self) -> Session:
        return self.session_factory()

class BaseRepository:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager


class UserRepository(BaseRepository):
    async def create_tables(self):
        await asyncio.to_thread(self.db_manager.create_db_and_tables)
        await self._init_default_settings()

    async def _init_default_settings(self):
        def _sync_init():
            default_settings = {
                'maintenance_mode': '0',
                'scheduler_on': '1',
                'btn_schedule': '1',
                'btn_search': '1',
                'btn_favorites': '1',
                'btn_settings': '1',
                'btn_free_rooms': '1'
            }
            with self.db_manager.get_session() as session:
                for key, value in default_settings.items():
                    statement = select(BotSetting).where(BotSetting.key == key)
                    result = session.execute(statement)
                    if not result.scalar_one_or_none():
                        session.add(BotSetting(key=key, value=value))
                session.commit()
        await asyncio.to_thread(_sync_init)

    async def get_settings(self) -> dict:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(BotSetting)
                result = session.execute(statement)
                rows = result.scalars().all()
                return {row.key: row.value for row in rows}
        return await asyncio.to_thread(_sync_get)

    async def update_setting(self, key: str, value: str):
        def _sync_update():
            with self.db_manager.get_session() as session:
                statement = select(BotSetting).where(BotSetting.key == key)
                result = session.execute(statement)
                setting = result.scalar_one_or_none()
                if setting:
                    setting.value = value
                else:
                    session.add(BotSetting(key=key, value=value))
                session.commit()
        await asyncio.to_thread(_sync_update)

    async def update_user_setting(self, user_id: int, setting_field: str, new_value: bool):
        def _sync_update():
            with self.db_manager.get_session() as session:
                statement = select(User).where(User.telegram_id == user_id)
                result = session.execute(statement)
                user = result.scalar_one_or_none()
                if not user: return
                
                settings = user.settings
                setattr(settings, setting_field, new_value)
                user.settings = settings
                session.commit()
        await asyncio.to_thread(_sync_update)

    async def upsert_user(self, user: User):
        def _sync_upsert():
            with self.db_manager.get_session() as session:
                stmt = select(User).where(User.telegram_id == user.telegram_id)
                res = session.execute(stmt)
                exists = res.scalar_one_or_none()
                if exists:
                    data = user.model_dump(exclude={"telegram_id"})
                    for key, value in data.items():
                        setattr(exists, key, value)
                else:
                    session.add(user)
                session.commit()
        await asyncio.to_thread(_sync_upsert)

    async def get_user(self, telegram_id: int) -> Optional[User]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(User).where(User.telegram_id == telegram_id)
                result = session.execute(statement)
                return result.scalar_one_or_none()
        return await asyncio.to_thread(_sync_get)

    async def get_users_by_group(self, group_name: str) -> List[User]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(User).where(User.group_name == group_name)
                result = session.execute(statement)
                return list(result.scalars().all())
        return await asyncio.to_thread(_sync_get)

class ScheduleRepository(BaseRepository):
    async def get_lessons_for_groups(self, group_names: List[str], target_date: date) -> List[Lesson]:
        if not group_names: return []
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(Lesson).where(
                    Lesson.date == target_date.isoformat(),
                    Lesson.group_name.in_(group_names)
                )
                result = session.execute(statement)
                return list(result.scalars().all())
        return await asyncio.to_thread(_sync_get)

    async def get_all_group_names(self) -> List[str]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(Lesson.group_name).distinct().order_by(Lesson.group_name)
                result = session.execute(statement)
                return list(result.scalars().all())
        return await asyncio.to_thread(_sync_get)

    async def get_lessons(self, group_name: str, target_date: date) -> List[Lesson]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(Lesson).where(
                    Lesson.group_name == group_name,
                    Lesson.date == target_date.isoformat()
                ).order_by(Lesson.pair_number)
                result = session.execute(statement)
                return list(result.scalars().all())
        return await asyncio.to_thread(_sync_get)

    async def search_groups(self, query: str) -> List[str]:
        query_clean = query.strip().lower()
        if not query_clean: return []
        def _sync_search():
            with self.db_manager.get_session() as session:
                # Fetch all distinct group names and filter in Python for proper Cyrillic support
                statement = select(Lesson.group_name).distinct()
                result = session.execute(statement)
                all_groups = list(result.scalars().all())
                
                matches = [g for g in all_groups if query_clean in g.lower()]
                matches.sort(key=lambda x: (
                    0 if x.lower() == query_clean 
                    else 1 if x.lower().startswith(query_clean) 
                    else 2
                ))
                return matches[:15]
        return await asyncio.to_thread(_sync_search)

    async def search_tracked_groups(self, query: str) -> List[str]:
        query_clean = query.strip().lower()
        if not query_clean: return []
        def _sync_search():
            with self.db_manager.get_session() as session:
                # Proper Cyrillic support by filtering in Python
                statement = select(TrackedGroup.group_name)
                result = session.execute(statement)
                all_groups = list(result.scalars().all())
                
                matches = [g for g in all_groups if query_clean in g.lower()]
                matches.sort(key=lambda x: (
                    0 if x.lower() == query_clean 
                    else 1 if x.lower().startswith(query_clean) 
                    else 2
                ))
                return matches[:15]
        return await asyncio.to_thread(_sync_search)

    async def get_tracked_groups_count(self) -> int:
        def _sync_count():
            with self.db_manager.get_session() as session:
                statement = select(func.count()).select_from(TrackedGroup)
                result = session.execute(statement)
                return result.scalar() or 0
        return await asyncio.to_thread(_sync_count)

    async def set_group_tracked(self, group_name: str, is_tracked: bool = True):
        def _sync_set():
            with self.db_manager.get_session() as session:
                statement = select(TrackedGroup).where(TrackedGroup.group_name == group_name)
                result = session.execute(statement)
                tg = result.scalar_one_or_none()
                if tg:
                    tg.is_tracked = is_tracked
                    session.commit()
        await asyncio.to_thread(_sync_set)

    async def get_predicted_schedule(self, group_name: str, target_date: date) -> List[Lesson]:
        def _sync_predict():
            # VyatSU usually has a 2-week cycle (14 days)
            # We look for lessons on the same day of the week, 
            # prioritizing those that match the 14-day phase (Numerator/Denominator)
            with self.db_manager.get_session() as session:
                # Find all lessons for this group on this weekday in the past 28 days
                weekday = target_date.weekday()
                raw_query = text("""
                    SELECT pair_number, subject, class_type, teacher, building, room, subgroup, date
                    FROM lesson
                    WHERE group_name = :group_name AND 
                          (strftime('%w', date) + 6) % 7 = :weekday
                    ORDER BY date DESC
                """)
                result = session.execute(raw_query, {
                    "group_name": group_name, 
                    "weekday": weekday
                })
                rows = result.fetchall()
                
                if not rows:
                    return []
                
                # Group by phase (date mod 14)
                # We need a reference date. Let's use the first date in the DB for this group as reference.
                ref_stmt = select(Lesson.date).where(Lesson.group_name == group_name).order_by(Lesson.date).limit(1)
                ref_date_str = session.execute(ref_stmt).scalar()
                if not ref_date_str: return []
                ref_date = date.fromisoformat(ref_date_str)
                
                target_phase = (target_date - ref_date).days % 14
                
                predicted = {}
                # First pass: try exact phase match (most accurate for 2-week cycle)
                for row in rows:
                    row_date = date.fromisoformat(row.date)
                    row_phase = (row_date - ref_date).days % 14
                    
                    if row_phase == target_phase:
                        p_num = row.pair_number
                        if p_num not in predicted:
                            predicted[p_num] = Lesson(
                                group_name=group_name,
                                date=target_date.isoformat(),
                                pair_number=p_num,
                                subject=row.subject,
                                class_type=row.class_type,
                                teacher=row.teacher,
                                building=row.building,
                                room=row.room,
                                subgroup=row.subgroup
                            )
                
                # Second pass: fill gaps with any weekday match if phase match failed
                for row in rows:
                    p_num = row.pair_number
                    if p_num not in predicted:
                         predicted[p_num] = Lesson(
                            group_name=group_name,
                            date=target_date.isoformat(),
                            pair_number=p_num,
                            subject=row.subject,
                            class_type=row.class_type,
                            teacher=row.teacher,
                            building=row.building,
                            room=row.room,
                            subgroup=row.subgroup
                        )
                
                return sorted(predicted.values(), key=lambda x: x.pair_number)
        return await asyncio.to_thread(_sync_predict)

    async def cleanup_old_lessons(self, weeks: int = 5):
        """Удаляет старые занятия из базы данных"""
        def _sync_cleanup():
            from datetime import timedelta
            cutoff_date = (date.today() - timedelta(weeks=weeks)).isoformat()
            with self.db_manager.get_session() as session:
                statement = delete(Lesson).where(Lesson.date < cutoff_date)
                session.execute(statement)
                session.commit()
                logging.info(f"🧹 База: Удалены занятия старше {cutoff_date}")
        await asyncio.to_thread(_sync_cleanup)

class OccupancyRepository(BaseRepository):
    async def get_occupied_rooms(self, target_date: date, pair_number: int, building: Optional[str] = None) -> Set[str]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(Occupancy).where(
                    Occupancy.date == target_date.isoformat(),
                    Occupancy.pair_number == pair_number,
                    Occupancy.is_free == False
                )
                if building: statement = statement.where(Occupancy.building == building)
                result = session.execute(statement)
                rows = result.scalars().all()
                if building: return {row.room for row in rows}
                return {f"{row.building}-{row.room}" for row in rows}
        return await asyncio.to_thread(_sync_get)

    async def get_all_rooms(self, building: Optional[str] = None) -> Set[str]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(Occupancy.building, Occupancy.room).distinct()
                if building: statement = statement.where(Occupancy.building == building)
                result = session.execute(statement)
                rows = result.all()
                if building: return {row[1] for row in rows}
                return {f"{row[0]}-{row[1]}" for row in rows}
        return await asyncio.to_thread(_sync_get)

    async def get_buildings(self) -> List[str]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                statement = select(Occupancy.building).distinct()
                result = session.execute(statement)
                buildings = [b for b in result.scalars().all() if b]
                try:
                    return sorted(buildings, key=lambda x: int(x) if x.isdigit() else 999)
                except (ValueError, TypeError):
                    return sorted(buildings)
        return await asyncio.to_thread(_sync_get)

    async def get_available_pairs(self, target_date: date, building: str) -> List[int]:
        def _sync_get():
            with self.db_manager.get_session() as session:
                # A pair is available if there is at least one free room in that building/date
                statement = select(Occupancy.pair_number).where(
                    Occupancy.date == target_date.isoformat(),
                    Occupancy.building == building,
                    Occupancy.is_free == True
                ).distinct().order_by(Occupancy.pair_number)
                result = session.execute(statement)
                return list(result.scalars().all())
        return await asyncio.to_thread(_sync_get)

    async def add_occupancy_batch(self, occupancies: List[Occupancy]):
        def _sync_add():
            with self.db_manager.get_session() as session:
                session.add_all(occupancies)
                session.commit()
        await asyncio.to_thread(_sync_add)

class AnalyticsRepository(BaseRepository):
    async def create_tables(self):
        await asyncio.to_thread(self.db_manager.create_db_and_tables)

    async def log_action(self, user_id: int, action: str, details: Optional[str] = None):
        def _sync_log():
            with self.db_manager.get_session() as session:
                log = ActionLog(user_id=user_id, action=action, details=details)
                session.add(log)
                session.commit()
        await asyncio.to_thread(_sync_log)

    async def cleanup_old_logs(self, days: int = 90):
        """Удаляет старые логи действий"""
        def _sync_cleanup():
            from datetime import timedelta
            cutoff_date = (date.today() - timedelta(days=days)).isoformat()
            with self.db_manager.get_session() as session:
                statement = delete(ActionLog).where(ActionLog.timestamp < cutoff_date)
                session.execute(statement)
                session.commit()
                logging.info(f"🧹 Аналитика: Удалены логи старше {cutoff_date}")
        await asyncio.to_thread(_sync_cleanup)