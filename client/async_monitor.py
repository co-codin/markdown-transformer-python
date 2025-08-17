#!/usr/bin/env python3
"""
Асинхронный монитор для параллельной проверки и скачивания результатов.
Использует asyncio и aiohttp для максимальной эффективности.
"""

import asyncio
import aiohttp
import time
import os
import sys
import json
import traceback
from typing import Dict, Set, List, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


class TaskStatus(Enum):
    """Статусы задач"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class Task:
    """Класс для хранения информации о задаче"""
    id: str
    filename: str
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    download_time: float = 0


class AsyncTaskMonitor:
    """Асинхронный монитор задач с параллельной загрузкой"""
    
    def __init__(self, tasks_file: str, output_dir: str, 
                 server_url: str = "http://localhost:8080",
                 max_concurrent: int = 5):
        """
        Args:
            tasks_file: файл с задачами
            output_dir: папка для результатов
            server_url: URL сервера
            max_concurrent: максимум одновременных запросов
        """
        self.tasks_file = tasks_file
        self.output_dir = output_dir
        self.server_url = server_url
        self.max_concurrent = max_concurrent
        
        # Словарь задач
        self.tasks: Dict[str, Task] = {}
        
        # Исходные данные из JSON для обновления
        self.original_data = None
        
        # Семафор для ограничения параллельных запросов
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # Создаем папку для результатов
        os.makedirs(output_dir, exist_ok=True)
        
        # Загружаем задачи
        self.load_tasks()
    
    def load_tasks(self):
        """Загружает информацию о задачах из файла"""
        try:
            with open(self.tasks_file, 'r') as f:
                self.original_data = json.load(f)
                for task_data in self.original_data.get('tasks', []):
                    # Пропускаем уже скачанные задачи (downloaded = True)
                    # и задачи с финальными статусами
                    downloaded_value = task_data.get('downloaded', False)
                    if downloaded_value is True or downloaded_value == "failed":
                        continue
                    
                    task = Task(
                        id=task_data['task_id'],
                        filename=task_data['file_name']
                    )
                    self.tasks[task.id] = task
                
                total_tasks = len(self.original_data.get('tasks', []))
                active_tasks = len(self.tasks)
                downloaded_tasks = total_tasks - active_tasks
                
                print(f"📊 Всего задач: {total_tasks}")
                if downloaded_tasks > 0:
                    print(f"   ✅ Уже скачано: {downloaded_tasks}")
                print(f"   📋 Активных задач: {active_tasks}")
        except FileNotFoundError:
            print(f"❌ Файл {self.tasks_file} не найден!")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Ошибка загрузки файла: {e}")
            sys.exit(1)
    
    async def check_task_status(self, session: aiohttp.ClientSession, task: Task) -> bool:
        """
        Проверяет статус одной задачи.
        
        Returns:
            True если задача готова к скачиванию
        """
        async with self.semaphore:
            try:
                url = f"{self.server_url}/api/v1/task/{task.id}"
                
                # Более длинный timeout для медленных соединений
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        status = data.get('status', 'pending')
                        
                        if status == 'completed':
                            task.status = TaskStatus.COMPLETED
                            print(f"   ✓ {task.filename}: готов к скачиванию")
                            return True
                        elif status == 'failed':
                            task.status = TaskStatus.FAILED
                            task.error_msg = data.get('message', 'Conversion failed')
                            print(f"   ❌ {task.filename}: {task.error_msg}")
                            # Обновим статус в original_data
                            self.update_task_status_in_data(task.id, "failed")
                            return False
                        elif status == 'processing':
                            task.status = TaskStatus.PROCESSING
                            print(f"   🔄 {task.filename}: обрабатывается")
                            # Обновим статус в original_data
                            self.update_task_status_in_data(task.id, "processing")
                            return False
                        elif status == 'pending':
                            return False
                        elif status == 'queued':
                            task.status = TaskStatus.PENDING
                            print(f"   ⏳ {task.filename}: в очереди на обработку")
                            return False
                        else:
                            print(f"   ⚠️ {task.filename}: неизвестный статус '{status}'")
                            return False
                            
                    elif response.status == 404:
                        task.status = TaskStatus.ERROR
                        task.error_msg = "Task not found on server"
                        print(f"   ❌ {task.filename}: задача не найдена на сервере")
                        # Помечаем как фантомную задачу
                        self.update_task_status_in_data(task.id, "not_found")
                        return False
                    else:
                        print(f"   ⚠️ {task.filename}: HTTP {response.status}")
                        return False
                    
            except asyncio.TimeoutError:
                print(f"   ⏱️ {task.filename}: ожидание. Сервер занят")
                return False
            except aiohttp.ClientError as e:
                print(f"   🔌 {task.filename}: ошибка соединения - {type(e).__name__}")
                return False
            except Exception as e:
                print(f"   ⚠️ {task.filename}: {type(e).__name__}: {str(e)}")
                return False
    
    async def download_task_result(self, session: aiohttp.ClientSession, task: Task) -> bool:
        """
        Скачивает результат одной задачи.
        
        Returns:
            True если успешно скачан
        """
        async with self.semaphore:
            try:
                start_time = time.time()
                url = f"{self.server_url}/api/v1/download/{task.id}"
                
                # Увеличенный timeout для скачивания
                timeout = aiohttp.ClientTimeout(total=60, connect=10)
                
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        content = await response.text()
                        
                        # Сохраняем файл
                        output_path = os.path.join(
                            self.output_dir, 
                            f"{task.filename}_{task.id}.txt"
                        )
                        
                        # Асинхронная запись в файл
                        await self.write_file_async(output_path, content)
                        
                        task.status = TaskStatus.DOWNLOADED
                        task.download_time = time.time() - start_time
                        
                        file_size = len(content) / 1024  # KB
                        print(f"   ✅ [{task.download_time:.2f}s] {task.filename} ({file_size:.1f} KB)")
                        return True
                    else:
                        task.status = TaskStatus.FAILED
                        task.error_msg = f"HTTP {response.status}"
                        print(f"   ⚠️ Не удалось скачать {task.filename}: HTTP {response.status}")
                        return False
                        
            except asyncio.TimeoutError:
                task.status = TaskStatus.FAILED
                task.error_msg = "Timeout при скачивании"
                print(f"   ⏱️ {task.filename}: timeout при скачивании")
                return False
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_msg = str(e)
                print(f"   ❌ Ошибка скачивания {task.filename}: {type(e).__name__}: {e}")
                return False
    
    async def write_file_async(self, path: str, content: str):
        """Асинхронная запись файла"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: open(path, 'w', encoding='utf-8').write(content)
        )
    
    def update_task_status_in_data(self, task_id: str, status: str):
        """Обновляет статус задачи в original_data"""
        if not self.original_data:
            return
        
        for task_data in self.original_data.get('tasks', []):
            if task_data['task_id'] == task_id:
                # Обновляем поле downloaded в зависимости от статуса
                if status == "processing":
                    task_data['downloaded'] = "processing"
                elif status == "failed":
                    task_data['downloaded'] = "failed"
                elif status == "not_found":
                    task_data['downloaded'] = "not_found"
                break
    
    async def save_tasks_to_json(self):
        """Сохраняет обновленные статусы задач обратно в JSON файл"""
        if not self.original_data:
            return
        
        # Обновляем статусы в исходных данных
        for task_data in self.original_data.get('tasks', []):
            task_id = task_data['task_id']
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == TaskStatus.DOWNLOADED:
                    task_data['downloaded'] = True  # Успешно скачано
                    task_data['downloaded_at'] = datetime.now().isoformat()
                elif task.status == TaskStatus.FAILED:
                    task_data['downloaded'] = "failed"  # Ошибка обработки
                    task_data['error'] = task.error_msg if task.error_msg else "Unknown error"
                elif task.status == TaskStatus.ERROR:
                    # Задача не найдена на сервере
                    if "not found" in task.error_msg.lower():
                        task_data['downloaded'] = "not_found"
                elif task.status == TaskStatus.PROCESSING:
                    task_data['downloaded'] = "processing"  # В обработке
        
        # Обновляем метаданные
        self.original_data['last_checked'] = datetime.now().isoformat()
        
        # Асинхронная запись в файл
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: json.dump(self.original_data, open(self.tasks_file, 'w'), indent=2)
        )
    
    async def process_single_task(self, session: aiohttp.ClientSession, task: Task):
        """Обрабатывает одну задачу: проверяет статус и скачивает если готова"""
        # Пропускаем уже обработанные
        if task.status in [TaskStatus.DOWNLOADED, TaskStatus.ERROR, TaskStatus.FAILED]:
            return
        
        # Проверяем статус
        is_ready = await self.check_task_status(session, task)
        
        # Если готова - скачиваем
        if is_ready:
            await self.download_task_result(session, task)
    
    async def test_connection(self, max_retries: int = 3) -> bool:
        """Тестирует соединение с сервером с retry логикой"""
        print(f"🔌 Проверка соединения с {self.server_url}...")
        
        for attempt in range(max_retries):
            try:
                # Увеличенный таймаут для медленного старта сервера
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"{self.server_url}/api/v1/health") as response:
                        if response.status == 200:
                            print("✅ Сервер доступен")
                            return True
                        else:
                            print(f"⚠️ Сервер ответил с кодом: {response.status}")
                            return True  # Сервер работает, но может быть другой endpoint
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1, 2, 4 секунды
                    print(f"⏱️ Timeout, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                    await asyncio.sleep(wait_time)
                else:
                    print("❌ Timeout - сервер не отвечает после всех попыток")
                    print("💡 Убедитесь, что сервер запущен")
                    return False
            except aiohttp.ClientConnectorError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"🔌 Не удается подключиться, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                    await asyncio.sleep(wait_time)
                else:
                    print("❌ Не удается подключиться к серверу")
                    print("💡 Убедитесь, что Docker контейнер запущен: docker-compose up -d")
                    return False
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"⚠️ Ошибка подключения: {e}, попытка {attempt + 1}/{max_retries}. Жду {wait_time}с...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ Ошибка подключения: {e}")
                    return False
        
        return False
    
    async def process_all_tasks(self) -> Tuple[int, int, int]:
        """
        Обрабатывает все задачи параллельно.
        
        Returns:
            (новые_скачанные, в_обработке, с_ошибками)
        """
        # Считаем текущее состояние до обработки
        before_downloaded = sum(1 for t in self.tasks.values() 
                               if t.status == TaskStatus.DOWNLOADED)
        
        # Настройки соединения (копируем из async_submit.py)
        connector = aiohttp.TCPConnector(
            limit=self.max_concurrent,
            force_close=True
        )
        
        timeout = aiohttp.ClientTimeout(
            total=60,  # Общий timeout
            connect=10,  # Timeout на подключение
            sock_connect=10,
            sock_read=30
        )
        
        try:
            async with aiohttp.ClientSession(
                connector=connector, 
                timeout=timeout,
                trust_env=True  # Использовать системные прокси если есть
            ) as session:
                # Создаем задачи для всех файлов
                tasks_to_process = [
                    self.process_single_task(session, task)
                    for task in self.tasks.values()
                ]
                
                # Запускаем все параллельно
                results = await asyncio.gather(*tasks_to_process, return_exceptions=True)
                
                # Проверяем на исключения
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        task_id = list(self.tasks.keys())[i]
                        print(f"   ⚠️ Ошибка обработки задачи {task_id}: {result}")
        
        except Exception as e:
            print(f"❌ Критическая ошибка при обработке: {e}")
            traceback.print_exc()
        
        # Подсчитываем результаты
        downloaded = sum(1 for t in self.tasks.values() 
                        if t.status == TaskStatus.DOWNLOADED)
        pending = sum(1 for t in self.tasks.values() 
                     if t.status in [TaskStatus.PENDING, TaskStatus.PROCESSING])
        errors = sum(1 for t in self.tasks.values() 
                    if t.status in [TaskStatus.ERROR, TaskStatus.FAILED])
        
        new_downloaded = downloaded - before_downloaded
        
        return new_downloaded, pending, errors
    
    def get_statistics(self) -> Dict:
        """Возвращает статистику обработки"""
        total = len(self.tasks)
        downloaded = sum(1 for t in self.tasks.values() 
                        if t.status == TaskStatus.DOWNLOADED)
        errors = sum(1 for t in self.tasks.values() 
                    if t.status in [TaskStatus.ERROR, TaskStatus.FAILED])
        pending = sum(1 for t in self.tasks.values() 
                     if t.status in [TaskStatus.PENDING, TaskStatus.PROCESSING])
        queued = sum(1 for t in self.tasks.values() 
                    if t.status == TaskStatus.PENDING)
        processing = sum(1 for t in self.tasks.values() 
                       if t.status == TaskStatus.PROCESSING)
        
        return {
            'total': total,
            'downloaded': downloaded,
            'errors': errors,
            'pending': pending,
            'queued': queued,
            'processing': processing,
            'progress': (downloaded / total * 100) if total > 0 else 0
        }
    
    async def monitor_loop(self, check_interval: int = 5):
        """Основной цикл мониторинга"""
        # Сначала проверяем соединение
        if not await self.test_connection():
            return
        
        print(f"\n⏱️  Проверка каждые {check_interval} секунд")
        print(f"🚀 Параллельная обработка до {self.max_concurrent} задач")
        print("🛑 Для остановки нажмите Ctrl+C")
        print("=" * 60)
        
        iteration = 0
        total_start_time = time.time()
        
        try:
            while True:
                iteration += 1
                iter_start = time.time()
                
                print(f"\n🔄 Итерация #{iteration} - {datetime.now().strftime('%H:%M:%S')}")
                print("-" * 40)
                
                # Обрабатываем все задачи параллельно
                new_downloaded, pending, errors = await self.process_all_tasks()
                
                # Сохраняем прогресс в JSON после каждой итерации
                if new_downloaded > 0 or errors > 0:
                    await self.save_tasks_to_json()
                
                # Получаем статистику
                stats = self.get_statistics()
                
                # Общее время работы
                total_elapsed = time.time() - total_start_time
                print(f"⏱️ Общее время работы: {total_elapsed:.1f}с")
                
                # Показываем новые скачивания
                if new_downloaded > 0:
                    print(f"🎉 Новых файлов скачано: {new_downloaded}")
                
                # Выводим статистику по статусам
                print(f"\n📊 Статус задач:")
                if stats['queued'] > 0:
                    print(f"   ⏳ В очереди: {stats['queued']}")
                if stats['processing'] > 0:
                    print(f"   🔄 Обрабатывается: {stats['processing']}")
                print(f"   ✅ Скачано: {stats['downloaded']}/{stats['total']}")
                if stats['errors'] > 0:
                    print(f"   ❌ С ошибками: {stats['errors']}")
                
                # Проверяем завершение
                if stats['pending'] == 0:
                    # Финальное сохранение
                    await self.save_tasks_to_json()
                    total_time = time.time() - total_start_time
                    print("\n✅ Все задачи обработаны!")
                    print(f"⏱️  Общее время: {total_time:.1f}с")
                    print(f"📊 Итоговая статистика:")
                    print(f"   • Успешно: {stats['downloaded']} файлов")
                    if stats['errors'] > 0:
                        print(f"   • С ошибками: {stats['errors']} файлов")
                    print(f"📁 Результаты: {os.path.abspath(self.output_dir)}")
                    print(f"💾 Прогресс сохранен в {self.tasks_file}")
                    break
                
                # Ожидание до следующей итерации
                print(f"\n⏳ Следующая проверка через {check_interval} секунд...")
                await asyncio.sleep(check_interval)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Остановлено пользователем")
            # Сохраняем прогресс перед выходом
            await self.save_tasks_to_json()
            stats = self.get_statistics()
            total_time = time.time() - total_start_time
            print(f"⏱️  Время работы: {total_time:.1f}с")
            print(f"📊 Скачано: {stats['downloaded']} из {stats['total']}")
            if stats['pending'] > 0:
                print(f"⏳ Осталось: {stats['pending']}")
            print(f"📁 Результаты: {os.path.abspath(self.output_dir)}")
            print(f"💾 Прогресс сохранен в {self.tasks_file}")


async def main():
    """Главная функция"""
    # Параметры
    tasks_file = "client/pending_tasks.json"
    output_dir = "./test_results"
    check_interval = 5  # секунд
    max_concurrent = 5  # уменьшено для стабильности
    
    # Можно передать интервал через аргумент
    if len(sys.argv) > 1:
        try:
            check_interval = int(sys.argv[1])
        except ValueError:
            pass
    
    # Создаем и запускаем монитор
    monitor = AsyncTaskMonitor(
        tasks_file=tasks_file,
        output_dir=output_dir,
        max_concurrent=max_concurrent
    )
    
    await monitor.monitor_loop(check_interval)


if __name__ == "__main__":
    print("🚀 Асинхронный монитор задач")
    
    # Запускаем асинхронный цикл
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")