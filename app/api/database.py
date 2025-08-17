import aiosqlite
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from app.config.settings import DB_PATH

logger = logging.getLogger(__name__)


class TaskDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_lock = asyncio.Lock()  # Только для инициализации
        self._supports_returning = False  # Будет проверено при инициализации
        
    @asynccontextmanager
    async def get_connection(self):
        """Главный метод для работы с БД."""
        db = await aiosqlite.connect(
            self.db_path,
            timeout=20.0
        )
        
        # Настройки один раз при подключении
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=10000")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=10000")  # 40MB кеша для ускорения запросов
        
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()
    
    async def _with_retry(self, operation, max_retries=3):
        """Простой retry для database locked."""
        for attempt in range(max_retries):
            try:
                return await operation()
            except aiosqlite.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (2 ** attempt))
                    continue
                raise
        
    async def init_db(self):
        async def _init():
            async with self.get_connection() as db:
                # Проверяем версию SQLite для поддержки RETURNING
                cursor = await db.execute("SELECT sqlite_version()")
                version_str = (await cursor.fetchone())[0]
                version_tuple = tuple(map(int, version_str.split(".")))
                self._supports_returning = version_tuple >= (3, 35, 0)
                logger.info(f"SQLite version: {version_str}, RETURNING support: {self._supports_returning}")
                
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT PRIMARY KEY,
                        original_filename TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        downloaded INTEGER DEFAULT 0,
                        result_path TEXT,
                        message TEXT,
                        progress INTEGER DEFAULT 0,
                        s3_url TEXT,
                        file_hash TEXT,
                        worker_id TEXT,
                        processing_started REAL
                    )
                ''')
                
                # Create indexes
                await db.execute('CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)')
                await db.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at)')
                await db.execute('CREATE INDEX IF NOT EXISTS idx_downloaded ON tasks(downloaded)')
                await db.execute('CREATE INDEX IF NOT EXISTS idx_file_hash ON tasks(file_hash)')  # Для быстрого поиска по hash
                
                # Новый индекс для статистики очереди
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_completed_recent
                    ON tasks(updated_at) WHERE status = 'completed'
                ''')
                
                await db.commit()
                
                # Запускаем миграции после создания базовой схемы
                await self.run_migrations()
                
                logger.info(f"Database initialized with WAL mode: {self.db_path}")
        
        async with self._init_lock:
            await self._with_retry(_init)
    
    async def run_migrations(self):
        """Запускает миграции БД с версионированием через PRAGMA user_version."""
        TARGET_SCHEMA_VERSION = 2
        
        async with self.get_connection() as db:
            # Получаем текущую версию схемы
            cursor = await db.execute("PRAGMA user_version")
            current_version = (await cursor.fetchone())[0]
            
            logger.info(f"Current DB schema version: {current_version}, target: {TARGET_SCHEMA_VERSION}")
            
            # Применяем миграции последовательно
            if current_version < 2:
                await self._migrate_to_v2(db)
                logger.info("Applied migration to v2")
            
            # Обновляем версию схемы
            if current_version < TARGET_SCHEMA_VERSION:
                await db.execute(f"PRAGMA user_version = {TARGET_SCHEMA_VERSION}")
                await db.commit()
                logger.info(f"Updated schema version to {TARGET_SCHEMA_VERSION}")
    
    async def _migrate_to_v2(self, db):
        """
        Миграция v1 -> v2: добавляет поддержку очереди задач.
        - Новые колонки: worker_id, processing_started
        - Новый статус: QUEUED
        - Новые индексы для производительности очереди
        """
        # Проверяем существующие колонки для идемпотентности
        cursor = await db.execute("PRAGMA table_info(tasks)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        # Добавляем новые колонки если их нет
        if 'worker_id' not in column_names:
            await db.execute("ALTER TABLE tasks ADD COLUMN worker_id TEXT")
            logger.info("Added worker_id column")
        
        if 'processing_started' not in column_names:
            await db.execute("ALTER TABLE tasks ADD COLUMN processing_started REAL")
            logger.info("Added processing_started column")
        
        # Мигрируем существующие данные
        # Все PENDING задачи становятся QUEUED для новой архитектуры
        await db.execute("""
            UPDATE tasks 
            SET status = 'queued' 
            WHERE status = 'pending'
        """)
        
        # Создаем индексы для оптимизации работы с очередью
        # idx_queue - для быстрого поиска следующей задачи в очереди
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue 
            ON tasks(status, created_at) 
            WHERE status = 'queued'
        """)
        
        # idx_worker - для поиска задач конкретного воркера
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_worker 
            ON tasks(worker_id, processing_started) 
            WHERE worker_id IS NOT NULL
        """)
        
        # idx_stale_tasks - для быстрого поиска зависших задач
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stale_tasks 
            ON tasks(status, processing_started) 
            WHERE status = 'processing'
        """)
        
        logger.info("Migration v2 completed: queue support added")
    
    async def create_task(self, task_id: str, task_data: Dict[str, Any]):
        async def _create():
            async with self.get_connection() as db:
                await db.execute('''
                    INSERT INTO tasks (
                        id, original_filename, status, created_at, updated_at,
                        message, progress, file_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task_id,
                    task_data['original_filename'],
                    task_data['status'],
                    datetime.now().timestamp(),
                    datetime.now().timestamp(),
                    task_data.get('message', ''),
                    task_data.get('progress', 0),
                    task_data.get('file_hash', None)  # Сохраняем hash файла для кеширования
                ))
                await db.commit()
        
        await self._with_retry(_create)
    
    async def update_task(self, task_id: str, updates: Dict[str, Any]):
        async def _update():
            # Защита от SQL-инъекций через whitelist полей
            ALLOWED_FIELDS = {'status', 'message', 'progress', 'result_path', 's3_url', 
                            'downloaded', 'worker_id', 'processing_started', 'file_hash'}
            
            # Фильтруем только разрешенные поля (используем новую переменную!)
            filtered_updates = {k: v for k, v in updates.items() if k in ALLOWED_FIELDS}
            filtered_updates['updated_at'] = datetime.now().timestamp()
            
            fields = ', '.join(f"{k} = ?" for k in filtered_updates.keys())
            values = list(filtered_updates.values()) + [task_id]
            
            async with self.get_connection() as db:
                await db.execute(
                    f"UPDATE tasks SET {fields} WHERE id = ?",
                    values
                )
                await db.commit()
        
        await self._with_retry(_update)
    
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        async with self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def get_task_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Найти успешно завершенную задачу по hash файла для кеширования."""
        async with self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM tasks 
                   WHERE file_hash = ? 
                   AND status = 'completed'
                   ORDER BY created_at DESC
                   LIMIT 1""", 
                (file_hash,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def get_pending_tasks(self) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('''
                SELECT * FROM tasks 
                WHERE status != 'failed' 
                AND downloaded = 0
                ORDER BY created_at DESC
            ''') as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def update_task_status(self, task_id: str, status: str, message: str = None):
        updates = {'status': status}
        if message:
            updates['message'] = message
        await self.update_task(task_id, updates)
    
    async def update_task_result(self, task_id: str, result_path: str, progress: int, s3_url: str = None):
        updates = {
            'result_path': result_path,
            'progress': progress
        }
        if s3_url:
            updates['s3_url'] = s3_url
        await self.update_task(task_id, updates)
    
    async def delete_task(self, task_id: str):
        """Delete a single task from database."""
        async def _delete():
            async with self.get_connection() as db:
                await db.execute(
                    "DELETE FROM tasks WHERE id = ?",
                    (task_id,)
                )
                await db.commit()
                logger.info(f"Deleted task {task_id} from database")
        
        await self._with_retry(_delete)
    
    async def cleanup_old_tasks(self, days: int = 7):
        async def _cleanup():
            cutoff_time = (datetime.now() - timedelta(days=days)).timestamp()
            
            async with self.get_connection() as db:
                # Get old tasks for file cleanup
                async with db.execute(
                    "SELECT id, result_path FROM tasks WHERE created_at < ?",
                    (cutoff_time,)
                ) as cursor:
                    old_tasks = await cursor.fetchall()
                
                # Delete from DB
                await db.execute(
                    "DELETE FROM tasks WHERE created_at < ?",
                    (cutoff_time,)
                )
                await db.commit()
                
                return old_tasks
        
        return await self._with_retry(_cleanup)
    
    async def cleanup_stale_processing_tasks(self) -> int:
        """
        Помечает все задачи в статусе PROCESSING как FAILED.
        Вызывается при старте сервера для очистки зависших задач от предыдущего запуска.
        
        Returns:
            Количество очищенных задач
        """
        async def _cleanup_stale():
            async with self.get_connection() as db:
                server_start_time = datetime.now().timestamp()
                
                # Обновляем все задачи в PROCESSING и PENDING на FAILED
                await db.execute("""
                    UPDATE tasks 
                    SET status = 'failed', 
                        message = 'Server was restarted while processing',
                        updated_at = ?
                    WHERE status IN ('processing', 'pending')
                """, (server_start_time,))
                
                # Получаем количество измененных строк
                cursor = await db.execute("SELECT changes()")
                row = await cursor.fetchone()
                await db.commit()
                
                count = row[0] if row else 0
                if count > 0:
                    logger.info(f"Marked {count} stale processing/pending tasks as failed")
                
                return count
        
        return await self._with_retry(_cleanup_stale)
    
    async def get_next_queued_task(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Атомарно захватывает следующую задачу из очереди для обработки.
        
        Args:
            worker_id: Идентификатор воркера для отслеживания
            
        Returns:
            Словарь с ПОЛНЫМИ данными захваченной задачи или None если очередь пуста
        """
        async def _get_next():
            async with self.get_connection() as db:
                db.row_factory = aiosqlite.Row  # Важно для получения имен колонок
                now = datetime.now().timestamp()
                
                if self._supports_returning:
                    # Современный SQLite с RETURNING (3.35.0+)
                    cursor = await db.execute("""
                        UPDATE tasks
                        SET status = 'processing',
                            worker_id = ?,
                            processing_started = ?,
                            updated_at = ?
                        WHERE id = (
                            SELECT id FROM tasks
                            WHERE status = 'queued'
                            ORDER BY created_at ASC
                            LIMIT 1
                        )
                        RETURNING *
                    """, (worker_id, now, now))
                    
                    row = await cursor.fetchone()
                    await db.commit()
                    
                    if row:
                        # Возвращаем полный словарь с данными задачи
                        return dict(row)
                    return None
                else:
                    # Fallback для старых версий SQLite
                    await db.execute("BEGIN IMMEDIATE")
                    try:
                        # Находим следующую задачу
                        cursor = await db.execute("""
                            SELECT id FROM tasks
                            WHERE status = 'queued'
                            ORDER BY created_at ASC
                            LIMIT 1
                        """)
                        
                        row = await cursor.fetchone()
                        if not row:
                            await db.rollback()
                            return None
                        
                        task_id = row[0] if isinstance(row, tuple) else row['id']
                        
                        # Захватываем её
                        await db.execute("""
                            UPDATE tasks
                            SET status = 'processing',
                                worker_id = ?,
                                processing_started = ?,
                                updated_at = ?
                            WHERE id = ? AND status = 'queued'
                        """, (worker_id, now, now, task_id))
                        
                        # Проверяем, что обновили ровно 1 строку
                        cursor = await db.execute("SELECT changes()")
                        changes = (await cursor.fetchone())[0]
                        
                        if changes == 1:
                            # Получаем ПОЛНЫЕ данные обновленной задачи
                            cursor = await db.execute("""
                                SELECT * FROM tasks WHERE id = ?
                            """, (task_id,))
                            row = await cursor.fetchone()
                            await db.commit()
                            
                            if row:
                                # Возвращаем полный словарь с данными задачи
                                return dict(row)
                            return None
                        else:
                            # Кто-то уже захватил эту задачу
                            await db.rollback()
                            return None
                    except Exception:
                        await db.rollback()
                        raise
        
        return await self._with_retry(_get_next)
    
    async def release_stale_tasks(self, timeout_seconds: int = 300) -> int:
        """
        Освобождает зависшие задачи, возвращая их в очередь.
        
        Args:
            timeout_seconds: Время в секундах после которого задача считается зависшей
            
        Returns:
            Количество освобожденных задач
        """
        async def _release():
            async with self.get_connection() as db:
                cutoff_time = datetime.now().timestamp() - timeout_seconds
                
                # Возвращаем зависшие задачи в очередь
                await db.execute("""
                    UPDATE tasks
                    SET status = 'queued',
                        worker_id = NULL,
                        processing_started = NULL,
                        message = 'Returned to queue after timeout',
                        updated_at = ?
                    WHERE status = 'processing'
                    AND processing_started < ?
                """, (datetime.now().timestamp(), cutoff_time))
                
                # Получаем количество освобожденных задач
                cursor = await db.execute("SELECT changes()")
                count = (await cursor.fetchone())[0]
                await db.commit()
                
                if count > 0:
                    logger.warning(f"Released {count} stale tasks back to queue")
                
                return count
        
        return await self._with_retry(_release)
    
    async def get_queue_statistics(self) -> Dict[str, Any]:
        """
        Получает статистику очереди одним оптимизированным запросом.
        
        Returns:
            Словарь со статистикой
        """
        async with self.get_connection() as db:
            hour_ago = datetime.now().timestamp() - 3600
            
            # Единый оптимизированный запрос для всей статистики
            cursor = await db.execute("""
                SELECT 
                    SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as queued,
                    SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    COUNT(*) as total,
                    COUNT(DISTINCT CASE WHEN status = 'processing' AND worker_id IS NOT NULL 
                          THEN worker_id END) as active_workers,
                    SUM(CASE WHEN status = 'completed' AND updated_at > ? THEN 1 ELSE 0 END) as completed_last_hour,
                    AVG(CASE WHEN status = 'completed' AND processing_started IS NOT NULL 
                        AND updated_at > ? 
                        THEN updated_at - processing_started END) as avg_processing_time
                FROM tasks
            """, (hour_ago, hour_ago))
            
            row = await cursor.fetchone()
            
            # Формируем результат
            stats = {
                'queued': row[0] or 0,
                'processing': row[1] or 0,
                'completed': row[2] or 0,
                'failed': row[3] or 0,
                'total': row[4] or 0,
                'active_workers': row[5] or 0,
                'processing_rate': round((row[6] or 0) / 60, 2),  # задач в минуту
                'avg_processing_time': round(row[7] or 0, 2)  # секунд на задачу
            }
            
            return stats


# Global instance
task_db = TaskDatabase()