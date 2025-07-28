#!/usr/bin/env python3
"""
Демонстрация мониторинга и скачивания результатов.
Запускает проверку каждые 10 секунд пока есть незавершенные задачи.
"""

import time
import os
import sys

# Добавляем путь к проекту
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from client.check_and_download import check_and_download_results


def monitor_and_download_loop(interval=10):
    """
    Запускает мониторинг и скачивание в цикле.
    
    Args:
        interval: интервал между проверками в секундах
    """
    
    print("🔄 Запуск мониторинга задач")
    print(f"⏱️  Проверка каждые {interval} секунд")
    print("🛑 Для остановки нажмите Ctrl+C")
    print("="*60)
    
    tasks_file = "demo_pending_tasks.json"
    dir_for_results = "./test_results"
    
    if not os.path.exists(tasks_file):
        print(f"❌ Файл {tasks_file} не найден!")
        print("💡 Сначала запустите: python client/demo_using_client.py")
        return
    
    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"\n🔄 Итерация #{iteration} - {time.strftime('%H:%M:%S')}")
            print("-" * 40)
            
            # Проверяем и скачиваем
            downloaded, pending = check_and_download_results(
                tasks_file=tasks_file,
                output_dir=dir_for_results,
                port=8000
            )
            
            # Если нет задач в обработке - завершаем
            if pending == 0 and downloaded == 0:
                print("\n✅ Все задачи обработаны!")
                print(f"📁 Результаты сохранены в: {os.path.abspath(dir_for_results)}")
                break
            
            # Ждем перед следующей проверкой
            if pending > 0:
                print(f"\n⏳ Ожидание {interval} секунд...")
                time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Мониторинг остановлен пользователем")
        print(f"📁 Скачанные результаты в: {os.path.abspath(dir_for_results)}")


if __name__ == "__main__":
    # Можно передать интервал как аргумент
    if len(sys.argv) > 1:
        try:
            interval = int(sys.argv[1])
        except ValueError:
            interval = 10
    else:
        interval = 10
        
    monitor_and_download_loop(interval)