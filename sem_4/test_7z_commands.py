import pytest
import time
import os
import binascii
import tempfile
import csv
import re
from pathlib import Path
from datetime import datetime
from conftest import config, TEST_DIR, EXTRACT_DIR, PERF_ARCHIVE_DIR, ARCHIVE_FILE


# Функция для проверки CRC
def verify_crc(output, filename, content):
    """Проверяет соответствие CRC в выводе команды 7z"""
    # Ищем строку с CRC в выводе
    crc_line = None
    filename_only = os.path.basename(filename)

    # Ищем строку, содержащую имя файла и значение CRC
    for line in output.splitlines():
        if filename_only in line:
            # Проверяем, содержит ли строка 8-значное шестнадцатеричное число
            if any(len(word) == 8 and all(c in '0123456789ABCDEF' for c in word) for word in line.split()):
                crc_line = line
                break

    if not crc_line:
        return False, f"No CRC found in output for {filename}. Output was:\n{output}"

    try:
        # Извлекаем значение CRC (первое 8-значное шестнадцатеричное число в строке)
        for word in crc_line.split():
            if len(word) == 8 and all(c in '0123456789ABCDEF' for c in word):
                crc_value = word.strip().upper()
                break
        else:
            return False, f"Can't parse CRC for {filename}"
    except Exception:
        return False, f"Can't parse CRC for {filename}"

    # Вычисляем ожидаемый CRC
    crc_func = binascii.crc32
    computed_crc = crc_func(content) if content else 0
    computed_crc = computed_crc & 0xFFFFFFFF
    computed_crc_hex = format(computed_crc, '08X')

    if crc_value == computed_crc_hex:
        return True, ""
    else:
        return False, f"CRC mismatch for {filename}: {crc_value} != {computed_crc_hex}"


def test_archive_listing(test_environment, ssh_client):
    """Тест команды просмотра содержимого архива (l) через SSH"""
    archive_type = config.get('archive', {}).get('type', '7z')

    # Выполняем команду просмотра архива
    command = f"7z l -t{archive_type} {ARCHIVE_FILE}"
    result = ssh_client.run_ssh_command(command)

    # Проверяем наличие файлов в выводе
    for file_info in config['test_files']:
        assert file_info['path'] in result, f"File {file_info['path']} not found in archive listing"


def test_archive_extraction(test_environment, ssh_client):
    """Тест команды извлечения файлов (x) через SSH"""
    archive_type = config.get('archive', {}).get('type', '7z')

    # Создаем временную директорию для извлечения на сервере
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    remote_extract_dir = f"{EXTRACT_DIR}/remote_extract_{timestamp}"
    ssh_client.run_ssh_command(f"mkdir -p '{remote_extract_dir}'")

    # Извлекаем архив на сервере
    command = f"7z x -t{archive_type} '{ARCHIVE_FILE}' -o'{remote_extract_dir}' -y"
    ssh_client.run_ssh_command(command)

    # Создаем временную локальную директорию для скачивания
    with tempfile.TemporaryDirectory() as temp_dir:
        local_extract_dir = Path(temp_dir) / f"remote_extract_{timestamp}"
        local_extract_dir.mkdir(parents=True, exist_ok=True)

        # Скачиваем извлеченные файлы для проверки
        ssh_client.download_directory(remote_extract_dir, str(local_extract_dir))

        # Проверяем наличие файлов
        for file_info in config['test_files']:
            local_file = local_extract_dir / file_info['path']
            assert local_file.exists(), f"File {file_info['path']} not extracted"


def test_hash_calculation(test_environment, ssh_client):
    """Тест расчета хеш-сумм файлов через SSH"""
    for file_info in config['test_files']:
        test_file = f"{TEST_DIR}/{file_info['path']}"

        # Экранируем путь к файлу
        command = f"7z h -scrcCRC32 '{test_file}'"
        result = ssh_client.run_ssh_command(command)

        # Подготовка содержимого для проверки
        content = None
        if file_info['content']:
            if file_info['type'] == 'binary':
                content = binascii.unhexlify(file_info['content'])
            else:
                content = file_info['content'].encode('utf-8')

        # Проверка CRC
        status, message = verify_crc(result, test_file, content)
        assert status, message


def test_temp_file_hash(ssh_client):
    """Тест хеширования временного файла с разным содержимым через SSH"""
    test_contents = [
        b"Simple content",
        b"",
        b"\x00\x01\x02\x03\xFF",
        "Тест на русском".encode('utf-8')
    ]

    # Создаем временную директорию на сервере
    remote_temp_dir = f"{TEST_DIR}/temp_hash_tests"
    ssh_client.run_ssh_command(f"mkdir -p '{remote_temp_dir}'")

    for content in test_contents:
        tmp_path = None
        remote_path = None
        try:
            # Создаем временный файл локально
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            # Используем временную директорию на сервере
            remote_filename = f"temp_{os.path.basename(tmp_path)}"
            remote_path = f"{remote_temp_dir}/{remote_filename}"

            # Копируем файл на сервер
            ssh_client.upload_file(tmp_path, remote_path)

            # Выполняем команду расчета хеша
            command = f"7z h -scrcCRC32 '{remote_path}'"
            result = ssh_client.run_ssh_command(command)

            # Проверяем корректность CRC
            status, message = verify_crc(result, remote_path, content)
            assert status, message

        finally:
            # Удаляем временные файлы
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # Очищаем временную директорию
    ssh_client.run_ssh_command(f"rm -rf '{remote_temp_dir}'", check=False)


# Функции для мониторинга CPU
def start_cpu_monitor(ssh_client, duration):
    """Запускает мониторинг CPU и возвращает имя файла с логами"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    log_file = f"/tmp/cpu_log_{timestamp}.txt"
    # Запускаем mpstat в фоновом режиме
    ssh_client.run_ssh_command(f"mpstat 1 {duration} > {log_file} &")
    return log_file


def parse_max_cpu(ssh_client, log_file):
    """Анализирует лог CPU и возвращает максимальную загрузку"""
    # Скачиваем лог-файл
    local_log = f"cpu_logs/{os.path.basename(log_file)}"
    os.makedirs(os.path.dirname(local_log), exist_ok=True)
    ssh_client.download_file(log_file, local_log)

    max_cpu = 0
    try:
        with open(local_log, 'r') as f:
            for line in f:
                if 'all' in line:
                    # Ищем строки вида: "04:25:07 PM  all    5.00    0.00    1.00    0.00    0.00    0.00    0.00    0.00   94.00"
                    parts = line.split()
                    if len(parts) >= 12:
                        # Последнее значение - %idle
                        idle = float(parts[-1])
                        usage = 100.0 - idle
                        if usage > max_cpu:
                            max_cpu = usage
    except Exception as e:
        print(f"Ошибка при анализе лога CPU: {str(e)}")

    # Удаляем лог на сервере
    ssh_client.run_ssh_command(f"rm -f {log_file}", check=False)
    return round(max_cpu, 1)


# Получаем тест-кейсы производительности
test_cases = config['performance']['test_cases']


@pytest.mark.parametrize("test_case", test_cases, ids=lambda tc: tc['name'])
def test_file_performance(make_files, test_case, ssh_client):
    """Параметризованный тест производительности через SSH"""
    # Проверяем доступность mpstat
    try:
        ssh_client.run_ssh_command("which mpstat")
        cpu_monitoring = True
    except:
        cpu_monitoring = False
        print("Утилита mpstat не установлена, мониторинг CPU отключен")

    files = make_files(test_case['file_sizes'], prefix=test_case['name'])

    # Мониторинг CPU для архивации
    cpu_log_archive = None
    if cpu_monitoring:
        # Предполагаемое время выполнения = размер * 2 секунды
        duration = max(10, test_case['total_size'] * 2)
        cpu_log_archive = start_cpu_monitor(ssh_client, duration)

    # Тестирование архивации
    archive_file = f"{PERF_ARCHIVE_DIR}/archive_{test_case['name']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.7z"
    start_time = time.time()
    file_list = " ".join([f"'{f}'" for f in files])
    ssh_client.run_ssh_command(f"7z a -t7z '{archive_file}' {file_list}")
    end_time = time.time()

    # Получаем данные о CPU для архивации
    max_cpu_archive = 'N/A'
    if cpu_monitoring and cpu_log_archive:
        max_cpu_archive = parse_max_cpu(ssh_client, cpu_log_archive)

    duration = end_time - start_time
    speed = test_case['total_size'] / duration if duration > 0 else 0

    # Запись результатов в CSV
    with open("performance_results.csv", "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            test_case['name'],
            "Archive",
            test_case['total_size'],
            test_case['file_count'],
            datetime.fromtimestamp(start_time).isoformat(),
            datetime.fromtimestamp(end_time).isoformat(),
            f"{duration:.2f}",
            f"{speed:.2f}",
            max_cpu_archive
        ])

    # Мониторинг CPU для распаковки
    cpu_log_extract = None
    if cpu_monitoring:
        # Предполагаемое время выполнения = размер * 1 секунда
        duration = max(10, test_case['total_size'])
        cpu_log_extract = start_cpu_monitor(ssh_client, duration)

    # Тестирование извлечения
    extract_dir = f"{EXTRACT_DIR}/extract_{test_case['name']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    ssh_client.run_ssh_command(f"mkdir -p '{extract_dir}'")

    start_time = time.time()
    ssh_client.run_ssh_command(f"7z x '{archive_file}' -o'{extract_dir}' -y")
    end_time = time.time()

    # Получаем данные о CPU для распаковки
    max_cpu_extract = 'N/A'
    if cpu_monitoring and cpu_log_extract:
        max_cpu_extract = parse_max_cpu(ssh_client, cpu_log_extract)

    duration = end_time - start_time
    speed = test_case['total_size'] / duration if duration > 0 else 0

    with open("performance_results.csv", "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            test_case['name'],
            "Extract",
            test_case['total_size'],
            test_case['file_count'],
            datetime.fromtimestamp(start_time).isoformat(),
            datetime.fromtimestamp(end_time).isoformat(),
            f"{duration:.2f}",
            f"{speed:.2f}",
            max_cpu_extract
        ])

    # Очистка
    ssh_client.run_ssh_command(f"rm -f '{archive_file}'", check=False)
    ssh_client.run_ssh_command(f"rm -rf '{extract_dir}'", check=False)


@pytest.fixture(scope="session", autouse=True)
def final_report():
    """Фикстура для генерации финального отчета"""
    yield

    # Чтение результатов
    try:
        import pandas as pd
        df = pd.read_csv("performance_results.csv")

        print("\n\nСравнительная таблица производительности:")
        print("-----------------------------------------------------------------------------------------")
        print("Тест                 | Операция   | Размер (MB) | Время (сек)  | Скорость (MB/s) | Max CPU (%)")
        print("-----------------------------------------------------------------------------------------")

        for _, row in df.iterrows():
            print(
                f"{row['Test Case'][:20]:<20} | {row['Operation']:<10} | {row['Total Size (MB)']:>11} | {row['Duration (s)']:>12} | {row['Speed (MB/s)']:>14} | {row['Max CPU (%)']:>11}")

        print("\nСводка по тест-кейсам:")
        print("-----------------------------------------------------------------------------------------")
        grouped = df.groupby(['Test Case', 'Operation']).agg({
            'Total Size (MB)': 'first',
            'Duration (s)': 'mean',
            'Speed (MB/s)': 'mean',
            'Max CPU (%)': 'max'
        })
        print(grouped)

    except ImportError:
        print("Для генерации отчета установите pandas: pip install pandas")
    except Exception as e:
        print(f"Ошибка при генерации отчета: {str(e)}")