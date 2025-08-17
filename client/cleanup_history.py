#!/usr/bin/env python3
"""
Утилита для очистки истории задач из файла pending_tasks.json и базы данных сервера
"""

import os
import sys
import json
import sqlite3
import requests
from datetime import datetime
from typing import List, Tuple

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def check_server_task_status(task_id: str, server_url: str = "http://localhost:8080") -> str:
    """
    Проверяет статус задачи на сервере.
    
    Args:
        task_id: ID задачи
        server_url: URL сервера
        
    Returns:
        Статус задачи: 'completed', 'failed', 'processing', 'pending' или 'unknown'
    """
    try:
        response = requests.get(f"{server_url}/api/v1/task/{task_id}", timeout=2)
        if response.status_code == 200:
            return response.json().get('status', 'unknown')
    except:
        pass
    return 'unknown'


def cleanup_server_database(db_path: str = "app/tasks.db", statuses_to_clean: List[str] = ['failed']) -> Tuple[int, int]:
    """
    Очищает задачи с определенными статусами из базы данных сервера.
    
    Args:
        db_path: путь к базе данных
        statuses_to_clean: список статусов для удаления
        
    Returns:
        Кортеж (количество удаленных задач, общее количество задач до очистки)
    """
    if not os.path.exists(db_path):
        return 0, 0
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Считаем общее количество задач
    cursor.execute("SELECT COUNT(*) FROM tasks")
    total = cursor.fetchone()[0]
    
    # Удаляем задачи с указанными статусами
    placeholders = ','.join('?' * len(statuses_to_clean))
    cursor.execute(f"DELETE FROM tasks WHERE status IN ({placeholders})", statuses_to_clean)
    deleted = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return deleted, total


def cleanup_task_history(tasks_file="client/pending_tasks.json", keep_active=True, check_server=False, clean_failed=False):
    """
    Очищает историю задач из файла и опционально из БД сервера.
    
    Args:
        tasks_file: путь к файлу с задачами
        keep_active: сохранять ли активные (не скачанные) задачи
        check_server: проверять ли статус задач на сервере
        clean_failed: очищать ли failed задачи из БД сервера
    """
    
    if not os.path.exists(tasks_file):
        print(f"❌ Файл {tasks_file} не найден")
        return
    
    # Загружаем задачи
    with open(tasks_file, 'r') as f:
        data = json.load(f)
    
    if not data.get('tasks'):
        print("📋 Нет задач для очистки в JSON файле")
    else:
        total_tasks = len(data['tasks'])
        
        if check_server:
            # Проверяем статус задач на сервере и помечаем failed
            print("🔍 Проверяем статусы задач на сервере...")
            failed_count = 0
            for task in data['tasks']:
                status = check_server_task_status(task['task_id'])
                task['server_status'] = status
                if status == 'failed':
                    task['failed'] = True
                    failed_count += 1
            print(f"   Найдено {failed_count} задач со статусом failed")
        
        if keep_active:
            # Оставляем только не скачанные и не failed задачи
            active_tasks = [t for t in data['tasks'] 
                          if not t.get('downloaded') and not t.get('failed')]
            removed_count = total_tasks - len(active_tasks)
            
            data['tasks'] = active_tasks
            action = "завершенных/ошибочных задач"
        else:
            # Удаляем все задачи
            removed_count = total_tasks
            data['tasks'] = []
            action = "всех задач"
        
        # Обновляем метаданные
        data['last_updated'] = datetime.now().isoformat()
        data['last_cleaned'] = datetime.now().isoformat()
        
        # Сохраняем обновленный файл
        with open(tasks_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"🧹 Очистка JSON файла завершена!")
        print(f"📊 Удалено {removed_count} из {total_tasks} {action}")
        print(f"📋 Осталось активных задач: {len(data['tasks'])}")
    
    # Очистка БД сервера
    if clean_failed:
        print("\n🗄️  Очистка базы данных сервера...")
        deleted, total = cleanup_server_database(statuses_to_clean=['failed', 'error'])
        if deleted > 0:
            print(f"   Удалено {deleted} задач с ошибками из БД (всего было {total})")
        else:
            print(f"   Нет задач с ошибками в БД")


def main():
    """Главная функция утилиты."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Очистка истории задач и ошибок',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python cleanup_history.py                     # Очистить скачанные задачи
  python cleanup_history.py --all               # Удалить все задачи
  python cleanup_history.py --check-server      # Проверить статусы на сервере
  python cleanup_history.py --clean-failed      # Очистить failed из БД сервера
  python cleanup_history.py --check-server --clean-failed  # Полная очистка
        """
    )
    parser.add_argument(
        'file', 
        nargs='?', 
        default='client/pending_tasks.json',
        help='Путь к файлу с задачами (по умолчанию: client/pending_tasks.json)'
    )
    parser.add_argument(
        '--all', 
        action='store_true',
        help='Удалить все задачи, включая активные'
    )
    parser.add_argument(
        '--check-server',
        action='store_true',
        help='Проверить статус задач на сервере и пометить failed'
    )
    parser.add_argument(
        '--clean-failed',
        action='store_true',
        help='Очистить задачи со статусом failed из БД сервера'
    )
    parser.add_argument(
        '--server-url',
        default='http://localhost:8080',
        help='URL сервера (по умолчанию: http://localhost:8080)'
    )
    
    args = parser.parse_args()
    
    cleanup_task_history(
        tasks_file=args.file,
        keep_active=not args.all,
        check_server=args.check_server,
        clean_failed=args.clean_failed
    )


if __name__ == "__main__":
    main()