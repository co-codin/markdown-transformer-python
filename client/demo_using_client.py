#!/usr/bin/env python3
"""
Демонстрация использования клиента для отправки тестовых файлов.
"""

import os
import sys

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from client.submit_tasks import submit_files

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
        "test_files/file_example_XLSX_50.xlsx",
        "test_files/pg76494-images-3.epub"
    ]
    
    # Проверяем существование файлов
    existing_files = []
    for file_path in test_files:
        if os.path.exists(file_path):
            existing_files.append(file_path)
        else:
            print(f"⚠️  Файл не найден: {file_path}")
    
    return existing_files


def submit_files_for_conversion():
    """Отправляет тестовые файлы на конвертацию через API."""
    
    print("🚀 Демонстрация отправки файлов на конвертацию")
    print("="*60)
    
    # Получаем список файлов
    files = get_test_files()
    
    if not files:
        print("❌ Нет файлов для отправки")
        return
    
    print(f"📋 Найдено файлов для отправки: {len(files)}\n")
    
    # Вызываем функцию отправки
    success_count, pending_tasks = submit_files(
        files=files,
        port=8000,
        tasks_file="demo_pending_tasks.json"
    )
    
    if success_count > 0:
        print("\n✅ Файлы успешно отправлены!")
        print("🔍 Для мониторинга используйте:")
        print("   python client/monitor_demo.py")


if __name__ == "__main__":
    submit_files_for_conversion()