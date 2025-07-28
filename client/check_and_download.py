#!/usr/bin/env python3
"""
Проверка статуса задач и скачивание готовых результатов.
"""

import os
import sys
import json
from datetime import datetime

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from client.base_client import AnyToMdClient


def check_and_download_results(tasks_file="pending_tasks.json", output_dir="download_results", port=8080):
    """
    Проверяет статус задач и скачивает готовые результаты.
    
    Args:
        tasks_file: файл с ID задач
        output_dir: директория для сохранения результатов
        port: порт сервиса
        
    Returns:
        (downloaded_count, pending_count) - количество скачанных и ожидающих задач
    """
    
    # Проверяем наличие файла с задачами
    if not os.path.exists(tasks_file):
        print(f"❌ Файл {tasks_file} не найден")
        return 0, 0
    
    # Загружаем задачи
    with open(tasks_file, 'r') as f:
        pending_tasks = json.load(f)
    
    if not pending_tasks.get('tasks'):
        print("📋 Нет задач для проверки")
        return 0, 0
    
    # Создаем клиент
    client = AnyToMdClient(f"http://localhost:{port}")
    
    # Создаем директорию для результатов
    os.makedirs(output_dir, exist_ok=True)
    
    # Проверяем каждую задачу
    downloaded_count = 0
    pending_count = 0
    failed_count = 0
    
    print(f"🔍 Проверка {len(pending_tasks['tasks'])} задач...")
    
    for task in pending_tasks['tasks']:
        if task.get('downloaded'):
            continue
            
        task_id = task['task_id']
        file_name = task['file_name']
        
        try:
            # Проверяем статус
            status = client.check_status(task_id)
            
            if status['status'] == 'completed':
                # Скачиваем результат
                print(f"📥 Скачивание {file_name} ({task_id})...", end='')
                
                output_path = os.path.join(output_dir, f"{file_name}_{task_id}.zip")
                client.download_result(task_id, output_path)
                
                # Помечаем как скачанный
                task['downloaded'] = True
                task['downloaded_at'] = datetime.now().isoformat()
                task['output_path'] = output_path
                
                downloaded_count += 1
                print(" ✅")
                
            elif status['status'] == 'failed':
                print(f"❌ {file_name}: {status.get('message', 'Ошибка конвертации')}")
                task['failed'] = True
                task['error'] = status.get('message', 'Unknown error')
                failed_count += 1
                
            else:
                # pending или processing
                pending_count += 1
                
        except Exception as e:
            print(f"❌ Ошибка при проверке {file_name}: {e}")
            pending_count += 1
    
    # Сохраняем обновленный файл
    pending_tasks['last_checked'] = datetime.now().isoformat()
    with open(tasks_file, 'w') as f:
        json.dump(pending_tasks, f, indent=2)
    
    # Выводим статистику
    total_tasks = len(pending_tasks['tasks'])
    completed_tasks = sum(1 for t in pending_tasks['tasks'] if t.get('downloaded'))
    
    print(f"\n📊 Статистика:")
    print(f"   Всего задач: {total_tasks}")
    print(f"   ✅ Скачано: {completed_tasks}")
    print(f"   📥 Скачано сейчас: {downloaded_count}")
    print(f"   ⏳ В обработке: {pending_count}")
    print(f"   ❌ С ошибками: {failed_count}")
    
    return downloaded_count, pending_count


if __name__ == "__main__":
    # Если вызван напрямую
    if len(sys.argv) > 1:
        tasks_file = sys.argv[1]
    else:
        tasks_file = "pending_tasks.json"
        
    check_and_download_results(tasks_file)