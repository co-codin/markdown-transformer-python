#!/usr/bin/env python3
"""
Утилита для очистки истории задач из файла pending_tasks.json
"""

import os
import sys
import json
from datetime import datetime

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def cleanup_task_history(tasks_file="demo_pending_tasks.json", keep_active=True):
    """
    Очищает историю задач из файла.
    
    Args:
        tasks_file: путь к файлу с задачами
        keep_active: сохранять ли активные (не скачанные) задачи
    """
    
    if not os.path.exists(tasks_file):
        print(f"❌ Файл {tasks_file} не найден")
        return
    
    # Загружаем задачи
    with open(tasks_file, 'r') as f:
        data = json.load(f)
    
    if not data.get('tasks'):
        print("📋 Нет задач для очистки")
        return
    
    total_tasks = len(data['tasks'])
    
    if keep_active:
        # Оставляем только не скачанные задачи
        active_tasks = [t for t in data['tasks'] if not t.get('downloaded')]
        removed_count = total_tasks - len(active_tasks)
        
        data['tasks'] = active_tasks
        action = "скачанных задач"
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
    
    print(f"🧹 Очистка завершена!")
    print(f"📊 Удалено {removed_count} из {total_tasks} {action}")
    print(f"📋 Осталось активных задач: {len(data['tasks'])}")


def main():
    """Главная функция утилиты."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Очистка истории задач')
    parser.add_argument(
        'file', 
        nargs='?', 
        default='demo_pending_tasks.json',
        help='Путь к файлу с задачами (по умолчанию: demo_pending_tasks.json)'
    )
    parser.add_argument(
        '--all', 
        action='store_true',
        help='Удалить все задачи, включая активные'
    )
    
    args = parser.parse_args()
    
    cleanup_task_history(
        tasks_file=args.file,
        keep_active=not args.all
    )


if __name__ == "__main__":
    main()