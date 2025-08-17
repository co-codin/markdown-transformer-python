#!/usr/bin/env python3
"""
Утилита для очистки задач из файла pending_tasks.json
Позволяет удалять задачи по статусу, времени и проверке на сервере
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def check_task_on_server(task_id: str, server_url: str = "http://localhost:8080") -> bool:
    """
    Проверяет существование задачи на сервере.
    
    Returns:
        True если задача существует, False если получили 404
    """
    try:
        response = requests.get(f"{server_url}/api/v1/task/{task_id}", timeout=2)
        return response.status_code != 404
    except:
        # При ошибке соединения считаем что задача может существовать
        return True


def filter_tasks_by_status(tasks: List[Dict], status_values: List[str]) -> List[Dict]:
    """
    Фильтрует задачи по значению поля downloaded.
    
    Args:
        tasks: список задач
        status_values: список значений для фильтрации
    
    Returns:
        Отфильтрованный список задач
    """
    if "all" in status_values:
        return tasks
    
    filtered = []
    for task in tasks:
        downloaded = task.get('downloaded', False)
        
        # Преобразуем строковые значения для сравнения
        if downloaded is True:
            downloaded_str = "true"
        elif downloaded is False:
            downloaded_str = "false"
        else:
            downloaded_str = str(downloaded)
        
        if downloaded_str in status_values:
            filtered.append(task)
    
    return filtered


def filter_tasks_by_age(tasks: List[Dict], hours: int) -> List[Dict]:
    """
    Фильтрует задачи по возрасту.
    
    Args:
        tasks: список задач
        hours: минимальный возраст в часах
    
    Returns:
        Задачи старше указанного времени
    """
    cutoff_time = datetime.now() - timedelta(hours=hours)
    filtered = []
    
    for task in tasks:
        submitted_at = task.get('submitted_at', '')
        if submitted_at:
            try:
                task_time = datetime.fromisoformat(submitted_at.replace('Z', '+00:00'))
                if task_time < cutoff_time:
                    filtered.append(task)
            except:
                # Если не можем распарсить время, пропускаем
                pass
    
    return filtered


def filter_tasks_by_server_check(tasks: List[Dict], server_url: str) -> List[Dict]:
    """
    Проверяет задачи на сервере и оставляет только несуществующие.
    
    Args:
        tasks: список задач
        server_url: URL сервера
    
    Returns:
        Задачи, которых нет на сервере
    """
    filtered = []
    print(f"🔍 Проверка {len(tasks)} задач на сервере...")
    
    for i, task in enumerate(tasks, 1):
        task_id = task.get('task_id', '')
        if not task_id:
            continue
        
        exists = check_task_on_server(task_id, server_url)
        if not exists:
            filtered.append(task)
            print(f"   [{i}/{len(tasks)}] ❌ {task_id[:8]}... - не найдена на сервере")
        else:
            print(f"   [{i}/{len(tasks)}] ✓ {task_id[:8]}... - существует на сервере")
    
    return filtered


def show_statistics(tasks: List[Dict], tasks_to_process: List[Dict]):
    """
    Показывает статистику по задачам.
    """
    print("\n📊 Статистика:")
    print(f"   Всего задач в файле: {len(tasks)}")
    print(f"   Найдено для обработки: {len(tasks_to_process)}")
    
    if tasks_to_process:
        # Группируем по статусам
        status_counts = {}
        for task in tasks_to_process:
            downloaded = task.get('downloaded', False)
            if downloaded is True:
                status = "true (скачано)"
            elif downloaded is False:
                status = "false (старый фантом)"
            else:
                status = f"{downloaded}"
            
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print("\n   Распределение по статусам:")
        for status, count in sorted(status_counts.items()):
            print(f"      • {status}: {count}")
        
        # Показываем примеры
        print("\n   Примеры задач (первые 3):")
        for task in tasks_to_process[:3]:
            task_id = task.get('task_id', 'NO_ID')[:8]
            filename = task.get('file_name', 'NO_NAME')
            submitted = task.get('submitted_at', 'NO_TIME')[:19]
            downloaded = task.get('downloaded', 'NO_STATUS')
            print(f"      • {task_id}... | {filename} | {submitted} | downloaded={downloaded}")


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(
        description='Очистка задач из JSON файла по различным критериям',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python cleanup_tasks.py --status_downloaded false              # Удалить старые фантомы
  python cleanup_tasks.py --status_downloaded sent --older-than 24  # Удалить старые отправленные
  python cleanup_tasks.py --status_downloaded "failed,not_found"    # Удалить ошибочные
  python cleanup_tasks.py --status_downloaded false --statistics    # Только показать статистику
  python cleanup_tasks.py --status_downloaded false --check-server  # Проверить на сервере
        """
    )
    
    parser.add_argument(
        '--status_downloaded',
        required=True,
        help='Значения поля downloaded для фильтрации (false, sent, processing, failed, not_found, true, all). Можно указать несколько через запятую'
    )
    parser.add_argument(
        '--file',
        default='client/pending_tasks.json',
        help='Путь к JSON файлу (по умолчанию: client/pending_tasks.json)'
    )
    parser.add_argument(
        '--older-than',
        type=int,
        metavar='HOURS',
        help='Обрабатывать только задачи старше N часов'
    )
    parser.add_argument(
        '--check-server',
        action='store_true',
        help='Проверить существование задач на сервере (удалить только несуществующие)'
    )
    parser.add_argument(
        '--statistics',
        action='store_true',
        help='Показать статистику без удаления'
    )
    parser.add_argument(
        '--server-url',
        default='http://localhost:8080',
        help='URL сервера (по умолчанию: http://localhost:8080)'
    )
    
    args = parser.parse_args()
    
    # Проверяем существование файла
    if not os.path.exists(args.file):
        print(f"❌ Файл {args.file} не найден")
        return
    
    # Загружаем задачи
    print(f"📂 Загрузка файла: {args.file}")
    with open(args.file, 'r') as f:
        data = json.load(f)
    
    tasks = data.get('tasks', [])
    if not tasks:
        print("📋 Нет задач в файле")
        return
    
    # Парсим статусы для фильтрации
    status_values = [s.strip() for s in args.status_downloaded.split(',')]
    print(f"🔍 Поиск задач со статусом downloaded: {status_values}")
    
    # Фильтруем по статусу
    tasks_to_process = filter_tasks_by_status(tasks, status_values)
    print(f"   Найдено: {len(tasks_to_process)} задач")
    
    # Фильтруем по времени если указано
    if args.older_than and tasks_to_process:
        print(f"⏰ Фильтрация по времени (старше {args.older_than} часов)...")
        tasks_to_process = filter_tasks_by_age(tasks_to_process, args.older_than)
        print(f"   Осталось: {len(tasks_to_process)} задач")
    
    # Проверяем на сервере если указано
    if args.check_server and tasks_to_process:
        tasks_to_process = filter_tasks_by_server_check(tasks_to_process, args.server_url)
        print(f"   Не найдено на сервере: {len(tasks_to_process)} задач")
    
    # Показываем статистику
    if args.statistics:
        show_statistics(tasks, tasks_to_process)
        return
    
    # Удаляем найденные задачи
    if not tasks_to_process:
        print("✅ Нет задач для удаления")
        return
    
    # Создаем новый список без удаляемых задач
    task_ids_to_remove = {t['task_id'] for t in tasks_to_process if 'task_id' in t}
    remaining_tasks = [t for t in tasks if t.get('task_id') not in task_ids_to_remove]
    
    # Обновляем данные
    data['tasks'] = remaining_tasks
    data['last_cleaned'] = datetime.now().isoformat()
    
    # Сохраняем файл
    with open(args.file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n🧹 Очистка завершена!")
    print(f"   Было задач: {len(tasks)}")
    print(f"   Удалено: {len(tasks_to_process)}")
    print(f"   Осталось: {len(remaining_tasks)}")
    print(f"💾 Файл обновлен: {args.file}")


if __name__ == "__main__":
    main()