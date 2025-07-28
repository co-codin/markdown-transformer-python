#!/usr/bin/env python3
"""
Отправка файлов на конвертацию и сохранение ID задач.
"""

import os
import sys
import json
from datetime import datetime

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from client.base_client import AnyToMdClient


def submit_files(files, port=8080, tasks_file="pending_tasks.json"):
    """
    Отправка файлов на конвертацию.
    
    Args:
        files: список путей к файлам
        port: порт сервиса
        tasks_file: файл для сохранения ID задач
    """
    
    print("📤 Отправка файлов на конвертацию")
    print(f"📡 Сервер: http://localhost:{port}")
    print(f"📁 Файлов для отправки: {len(files)}")
    print("="*60)
    
    # Создаем клиент
    client = AnyToMdClient(f"http://localhost:{port}")
    
    # Загружаем существующие задачи если файл есть
    if os.path.exists(tasks_file):
        with open(tasks_file, 'r') as f:
            pending_tasks = json.load(f)
        print(f"📋 Загружено {len(pending_tasks['tasks'])} существующих задач")
    else:
        pending_tasks = {
            "tasks": []
        }
    
    # Отправляем файлы
    success_count = 0
    for file_path in files:
        if not os.path.exists(file_path):
            print(f"⚠️  Файл не найден: {file_path}")
            continue
            
        try:
            result = client.convert_file(file_path)
            task_id = result.get('task_id')
            file_name = os.path.basename(file_path)
            file_ext = os.path.splitext(file_name)[1]
            print(f"✅ {file_name}: {task_id}")
            
            pending_tasks["tasks"].append({
                "task_id": task_id,
                "file_path": file_path,
                "file_name": file_name,
                "format": file_ext.lower().replace('.', ''),
                "submitted_at": datetime.now().isoformat(),
                "downloaded": False
            })
            success_count += 1
        except Exception as e:
            print(f"❌ {file_path}: {e}")
    
    # Обновляем временную метку
    pending_tasks["last_updated"] = datetime.now().isoformat()
    pending_tasks["server"] = f"http://localhost:{port}"
    
    # Сохраняем информацию о задачах
    with open(tasks_file, 'w') as f:
        json.dump(pending_tasks, f, indent=2)
    
    print(f"\n📊 Результаты:")
    print(f"✅ Успешно отправлено: {success_count}")
    print(f"❌ Ошибок: {len(files) - success_count}")
    print(f"💾 ID задач сохранены в: {tasks_file}")
    print(f"📋 Всего задач в очереди: {len(pending_tasks['tasks'])}")
    
    return success_count, pending_tasks


if __name__ == "__main__":
    # Если вызван напрямую, берем файлы из аргументов командной строки
    if len(sys.argv) > 1:
        files = sys.argv[1:]
        submit_files(files)
    else:
        print("❌ Не указаны файлы для отправки")
        print("Использование: python submit_tasks.py file1.pdf file2.docx ...")