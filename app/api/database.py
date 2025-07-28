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
                        progress INTEGER DEFAULT 0
                    )
                ''')
                
                # Create indexes
                await db.execute('CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)')
                await db.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at)')
                await db.execute('CREATE INDEX IF NOT EXISTS idx_downloaded ON tasks(downloaded)')
                
                await db.commit()
                logger.info(f"Database initialized with WAL mode: {self.db_path}")
        
        async with self._init_lock:
            await self._with_retry(_init)
    
    async def create_task(self, task_id: str, task_data: Dict[str, Any]):
        async def _create():
            async with self.get_connection() as db:
                await db.execute('''
                    INSERT INTO tasks (
                        id, original_filename, status, created_at, updated_at,
                        message, progress
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task_id,
                    task_data['original_filename'],
                    task_data['status'],
                    datetime.now().timestamp(),
                    datetime.now().timestamp(),
                    task_data.get('message', ''),
                    task_data.get('progress', 0)
                ))
                await db.commit()
        
        await self._with_retry(_create)
    
    async def update_task(self, task_id: str, updates: Dict[str, Any]):
        async def _update():
            updates['updated_at'] = datetime.now().timestamp()
            
            fields = ', '.join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [task_id]
            
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
    
    async def update_task_result(self, task_id: str, result_path: str, progress: int):
        await self.update_task(task_id, {
            'result_path': result_path,
            'progress': progress
        })
    
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


# Global instance
task_db = TaskDatabase()