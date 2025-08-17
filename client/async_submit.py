#!/usr/bin/env python3
"""
Асинхронная версия отправки файлов на сервер для обработки.
Ускоряет процесс за счет параллельной отправки множества файлов.
"""

import asyncio
import aiohttp
import aiofiles
import os
import sys
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


@dataclass
class UploadTask:
    """Информация о загружаемом файле"""
    filepath: str
    filename: str
    task_id: str = ""
    status: str = "pending"
    upload_time: float = 0
    error: str = ""
    file_size: int = 0
    format: str = ""


class AsyncFileUploader:
    """Асинхронный загрузчик файлов на сервер"""
    
    def __init__(self, 
                 server_url: str = "http://localhost:8080",
                 max_concurrent: int = 10,
                 tasks_file: str = "client/pending_tasks.json"):
        """
        Args:
            server_url: URL сервера
            max_concurrent: максимум параллельных загрузок
            tasks_file: файл для сохранения информации о задачах
        """
        self.server_url = server_url
        self.tasks_file = tasks_file
        self.max_concurrent = max_concurrent
        
        # Семафор для ограничения параллельных загрузок
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # Список задач
        self.tasks: List[UploadTask] = []
        self.successful_uploads = 0
        self.failed_uploads = 0
    
    async def read_file_async(self, filepath: str) -> bytes:
        """Асинхронное чтение файла"""
        async with aiofiles.open(filepath, 'rb') as f:
            return await f.read()
    
    def calculate_md5(self, content: bytes) -> str:
        """Вычисляет MD5 хеш содержимого файла"""
        return hashlib.md5(content).hexdigest()
    
    async def upload_single_file(self, session: aiohttp.ClientSession, task: UploadTask, max_retries: int = 3) -> bool:
        """
        Загружает один файл на сервер с retry логикой.
        
        Returns:
            True если успешно загружен
        """
        async with self.semaphore:
            # Читаем файл один раз перед всеми попытками
            try:
                file_content = await self.read_file_async(task.filepath)
                task.file_size = len(file_content)
            except FileNotFoundError:
                task.status = "failed"
                task.error = "Файл не найден"
                print(f"❌ {task.filename}: файл не найден")
                self.failed_uploads += 1
                return False
            except Exception as e:
                task.status = "failed"
                task.error = f"Ошибка чтения файла: {e}"
                print(f"❌ {task.filename}: ошибка чтения - {e}")
                self.failed_uploads += 1
                return False
            
            # Пробуем загрузить с retry логикой
            for attempt in range(max_retries):
                try:
                    start_time = time.time()
                    
                    # Подготавливаем данные для отправки
                    form_data = aiohttp.FormData()
                    form_data.add_field(
                        'file',
                        file_content,
                        filename=task.filename,
                        content_type='application/octet-stream'
                    )
                    
                    # Отправляем файл на правильный endpoint
                    url = f"{self.server_url}/api/v1/convert"
                    timeout = aiohttp.ClientTimeout(total=300, connect=30)
                    
                    async with session.post(url, data=form_data, timeout=timeout) as response:
                        if response.status == 200:
                            result = await response.json()
                            task.task_id = result.get('task_id', '')
                            task.status = "uploaded"
                            task.upload_time = time.time() - start_time
                            task.format = os.path.splitext(task.filename)[1].lower().replace('.', '')
                            
                            size_kb = task.file_size / 1024
                            speed_mbps = (task.file_size / 1024 / 1024) / task.upload_time if task.upload_time > 0 else 0
                            
                            print(f"✅ [{task.upload_time:.2f}s] {task.filename} "
                                  f"({size_kb:.1f} KB, {speed_mbps:.2f} MB/s) "
                                  f"ID: {task.task_id[:8]}...")
                            
                            self.successful_uploads += 1
                            return True
                        else:
                            error_text = await response.text()
                            if attempt < max_retries - 1:
                                wait_time = 2 ** attempt
                                print(f"⚠️ {task.filename}: HTTP {response.status}, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                                await asyncio.sleep(wait_time)
                            else:
                                task.status = "failed"
                                task.error = f"HTTP {response.status}: {error_text}"
                                print(f"❌ {task.filename}: {task.error}")
                                self.failed_uploads += 1
                                return False
                                
                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"⏱️ {task.filename}: timeout, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                        await asyncio.sleep(wait_time)
                    else:
                        task.status = "failed"
                        task.error = "Timeout при загрузке после всех попыток"
                        print(f"❌ {task.filename}: timeout после {max_retries} попыток")
                        self.failed_uploads += 1
                        return False
                        
                except aiohttp.ClientError as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"🔌 {task.filename}: ошибка соединения, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                        await asyncio.sleep(wait_time)
                    else:
                        task.status = "failed"
                        task.error = f"Ошибка соединения: {e}"
                        print(f"❌ {task.filename}: {type(e).__name__}: {e}")
                        self.failed_uploads += 1
                        return False
                        
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"⚠️ {task.filename}: {type(e).__name__}, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                        await asyncio.sleep(wait_time)
                    else:
                        task.status = "failed"
                        task.error = str(e)
                        print(f"❌ {task.filename}: {type(e).__name__}: {e}")
                        self.failed_uploads += 1
                        return False
            
            return False
    
    async def upload_files(self, file_paths: List[str]) -> Tuple[int, int]:
        """
        Загружает список файлов параллельно с прогресс-баром.
        
        Returns:
            (успешно_загружено, неудачно)
        """
        # Создаем задачи для каждого файла
        self.tasks = []
        for filepath in file_paths:
            filename = os.path.basename(filepath)
            task = UploadTask(filepath=filepath, filename=filename)
            self.tasks.append(task)
        
        print(f"📤 Загрузка {len(self.tasks)} файлов...")
        print(f"🚀 Параллельная загрузка до {self.max_concurrent} файлов")
        print("-" * 60)
        
        # Настройки соединения
        connector = aiohttp.TCPConnector(
            limit=self.max_concurrent,
            force_close=True
        )
        
        start_time = time.time()
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Создаем корутины для всех загрузок
            upload_coroutines = [
                self.upload_single_file(session, task)
                for task in self.tasks
            ]
            
            # Запускаем все параллельно с прогресс-баром
            results = []
            for i, coro in enumerate(asyncio.as_completed(upload_coroutines), 1):
                result = await coro
                # Показываем прогресс
                progress = (i / len(upload_coroutines)) * 100
                bar_filled = int(progress / 5)
                progress_bar = "█" * bar_filled + "░" * (20 - bar_filled)
                print(f"\r📊 Прогресс: [{progress_bar}] {progress:.0f}% ({i}/{len(upload_coroutines)})", 
                      end="", flush=True)
                results.append(result)
        
        print()  # Новая строка после прогресс-бара
        
        total_time = time.time() - start_time
        print("-" * 60)
        print(f"⏱️ Общее время: {total_time:.2f} секунд")
        
        # Сохраняем информацию о задачах
        await self.save_tasks_info()
        
        return self.successful_uploads, self.failed_uploads
    
    async def save_tasks_info(self):
        """Сохраняет информацию о загруженных задачах в файл"""
        # Загружаем существующие задачи если файл есть
        existing_tasks = []
        if os.path.exists(self.tasks_file):
            try:
                with open(self.tasks_file, 'r') as f:
                    data = json.load(f)
                    existing_tasks = data.get('tasks', [])
                    print(f"📋 Загружено {len(existing_tasks)} существующих задач")
            except:
                pass
        
        # Добавляем новые успешно загруженные задачи
        new_tasks = [
            {
                'task_id': task.task_id,
                'file_path': task.filepath,
                'file_name': task.filename,
                'format': task.format,
                'submitted_at': datetime.now().isoformat(),
                'downloaded': "sent",  # Изменено с False на "sent"
                'upload_time': task.upload_time,
                'file_size': task.file_size
            }
            for task in self.tasks
            if task.status == "uploaded" and task.task_id
        ]
        
        all_tasks = existing_tasks + new_tasks
        
        data = {
            'tasks': all_tasks,
            'last_updated': datetime.now().isoformat(),
            'server': self.server_url,
            'total_uploaded': len([t for t in all_tasks if not t.get('downloaded', False)]),
            'total_failed': self.failed_uploads
        }
        
        # Асинхронная запись в файл
        async with aiofiles.open(self.tasks_file, 'w') as f:
            await f.write(json.dumps(data, indent=2))
        
        print(f"\n💾 Информация о задачах сохранена в: {self.tasks_file}")
    
    async def test_connection(self, max_retries: int = 3) -> bool:
        """Проверяет соединение с сервером с retry логикой"""
        print(f"🔌 Проверка соединения с {self.server_url}...")
        
        for attempt in range(max_retries):
            try:
                # Увеличенный таймаут для медленного старта сервера
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"{self.server_url}/api/v1/health") as response:
                        if response.status == 200:
                            print("✅ Сервер доступен\n")
                            return True
                        else:
                            print(f"⚠️ Сервер ответил кодом: {response.status}\n")
                            return True
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1, 2, 4 секунды
                    print(f"⏱️ Timeout, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                    await asyncio.sleep(wait_time)
                else:
                    print("❌ Timeout - сервер не отвечает после всех попыток")
                    print("💡 Убедитесь, что сервер запущен: docker-compose up -d\n")
                    return False
            except aiohttp.ClientConnectorError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"🔌 Не удается подключиться, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                    await asyncio.sleep(wait_time)
                else:
                    print("❌ Не удается подключиться к серверу")
                    print("💡 Убедитесь, что Docker контейнер запущен: docker-compose up -d\n")
                    return False
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"⚠️ Ошибка: {e}, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ Ошибка подключения: {e}")
                    print("💡 Убедитесь, что сервер запущен\n")
                    return False
        
        return False


def get_test_files():
    """Возвращает список тестовых файлов для конвертации."""
    test_files = [
        "test_files/file-sample_100kB.doc",
        "test_files/file-sample_100kB.docx",
        "test_files/file-sample_100kB.odt",
        "test_files/test-image_150kB.pdf",
        "test_files/powerpoint_with_image.pptx",
        "test_files/sample.rtf",
        "test_files/file_example_XLS_50.xls",
        "test_files/file_example_XLSX_50.xlsx"
    ]
    
    # Можно дублировать файлы для тестирования параллельной загрузки
    # test_files = test_files * 2  # Удвоить список для теста
    
    # Проверяем существование файлов
    existing_files = []
    missing_files = []
    
    for file_path in test_files:
        if os.path.exists(file_path):
            existing_files.append(file_path)
        else:
            missing_files.append(file_path)
    
    if missing_files:
        print("⚠️ Не найдены файлы:")
        for f in missing_files:
            print(f"   • {f}")
        print()
    
    return existing_files


async def main():
    """Главная функция для асинхронной загрузки"""
    print("🚀 Асинхронная отправка файлов на конвертацию")
    print("=" * 60)
    
    # Получаем список файлов
    files = get_test_files()
    
    if not files:
        print("❌ Нет файлов для отправки")
        return
    
    print(f"📋 Найдено файлов для отправки: {len(files)}\n")
    
    # Создаем загрузчик
    uploader = AsyncFileUploader(
        server_url="http://localhost:8080",
        max_concurrent=5,  # Количество параллельных загрузок
        tasks_file="client/pending_tasks.json"
    )
    
    # Проверяем соединение
    if not await uploader.test_connection():
        return
    
    # Загружаем файлы
    start_time = time.time()
    success, failed = await uploader.upload_files(files)
    total_time = time.time() - start_time
    
    # Выводим итоги
    print("\n" + "=" * 60)
    print("📊 Итоги загрузки:")
    print(f"   ✅ Успешно загружено: {success}")
    if failed > 0:
        print(f"   ❌ Не удалось загрузить: {failed}")
    print(f"   ⏱️ Общее время: {total_time:.2f} секунд")
    if success > 0:
        print(f"   🚀 Средняя скорость: {total_time/success:.2f} сек/файл")
    
    if success > 0:
        print("\n✅ Файлы успешно отправлены!")
        print("🔍 Для мониторинга результатов используйте:")
        print("   python client/monitor_demo.py")
        print("   или")
        print("   python client/async_monitor.py")


if __name__ == "__main__":
    print("🚀 Запуск асинхронного загрузчика файлов\n")
    
    # Запускаем асинхронную загрузку
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Загрузка прервана пользователем")