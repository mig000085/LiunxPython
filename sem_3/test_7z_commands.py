import os
import subprocess
import pytest
import shutil
import tempfile
import binascii
import re
import time
import csv
from datetime import datetime
from pathlib import Path
from checkers import verify_extracted_files, verify_crc, verify_file_in_listing
from conftest import config, DATA_DIR, TEST_DIR, ARCHIVE_FILE, EXTRACT_DIR, PERF_ARCHIVE_DIR


# Подготовка ожидаемых файлов для базовых тестов
def get_expected_files():
    expected = []
    for file_info in config['test_files']:
        content = file_info['content']
        file_type = file_info['type']

        if file_type == 'binary' and content:
            content = binascii.unhexlify(content)
        elif file_type == 'text' and content:
            content = content.encode('utf-8')
        else:
            content = b''

        expected.append((file_info['path'], content))
    return expected


# Путь к CSV-файлу с результатами
PERF_RESULTS = Path("performance_results.csv")


# Фикстура для инициализации CSV-файла
@pytest.fixture(scope="session", autouse=True)
def init_csv_report():
    """Инициализация CSV-файла для результатов"""
    if PERF_RESULTS.exists():
        # Создаем резервную копию старого отчета
        backup_name = f"performance_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        PERF_RESULTS.rename(backup_name)

    # Создаем заголовки CSV
    with open(PERF_RESULTS, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "Test Case",
            "Operation",
            "Total Size (MB)",
            "File Count",
            "Start Time",
            "End Time",
            "Duration (s)",
            "Speed (MB/s)"
        ])


# -------------------- Базовые тесты функциональности --------------------

def test_archive_listing(test_environment):
    """Тест команды вывода списка файлов в архиве (l)"""
    archive_type = config.get('archive', {}).get('type', '7z')

    result = subprocess.run(
        ['7z', 'l', f'-t{archive_type}', str(ARCHIVE_FILE)],
        capture_output=True,
        text=True,
        check=True
    )

    for file_info in config['test_files']:
        assert verify_file_in_listing(result.stdout, file_info['path']), \
            f"Файл {file_info['path']} не найден в архиве"


def test_archive_extraction(test_environment):
    """Тест команды извлечения файлов (x)"""
    archive_type = config.get('archive', {}).get('type', '7z')

    if EXTRACT_DIR.exists():
        shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ['7z', 'x', f'-t{archive_type}', str(ARCHIVE_FILE), f'-o{EXTRACT_DIR}', '-y'],
        check=True
    )

    # Проверка извлеченных файлов
    expected_files = get_expected_files()
    status, message = verify_extracted_files(
        str(EXTRACT_DIR),
        str(TEST_DIR),
        expected_files
    )
    assert status, message


def test_hash_calculation(test_environment):
    """Тест расчета хеш-сумм файлов"""
    for file_info in config['test_files']:
        test_file = TEST_DIR / file_info['path']
        assert test_file.exists(), f"Тестовый файл {test_file} не существует"

        try:
            result = subprocess.run(
                ['7z', 'h', '-scrcCRC32', str(test_file)],
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            pytest.fail(f"Ошибка при расчете хеша для {test_file}: {e.stderr}")

        # Подготовка содержимого для проверки
        content = None
        if file_info['content']:
            if file_info['type'] == 'binary':
                content = binascii.unhexlify(file_info['content'])
            else:
                content = file_info['content'].encode('utf-8')

        # Проверка CRC
        status, message = verify_crc(result.stdout, str(test_file), content)
        assert status, message


def test_temp_file_hash():
    """Тест хеширования временного файла с разным содержимым"""
    test_contents = [
        b"Simple content",
        b"",
        b"\x00\x01\x02\x03\xFF",
        "Тест на русском".encode('utf-8')
    ]

    for content in test_contents:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ['7z', 'h', '-scrcCRC32', tmp_path],
                capture_output=True,
                text=True,
                check=True
            )

            # Проверка CRC
            status, message = verify_crc(result.stdout, tmp_path, content)
            assert status, message
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# -------------------- Тесты производительности --------------------

def run_performance_test(test_name, files, total_size, file_count):
    """Выполняет тест производительности и записывает результаты в CSV"""
    archive_type = config['archive'].get('type', '7z')
    archive_file = f"perf_archive_{test_name.replace(' ', '_')}.{archive_type}"
    archive_path = PERF_ARCHIVE_DIR / archive_file

    # Тест архивирования
    archive_start = time.time()
    archive_start_time = datetime.now().isoformat()
    subprocess.run(
        ['7z', 'a', f'-t{archive_type}', str(archive_path)] + [str(f) for f in files],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    archive_end = time.time()
    archive_duration = archive_end - archive_start
    archive_speed = total_size / archive_duration if archive_duration > 0 else 0

    # Запись результатов архивации в CSV
    with open(PERF_RESULTS, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            test_name,
            "Archive",
            total_size,
            file_count,
            archive_start_time,
            datetime.now().isoformat(),
            round(archive_duration, 3),
            round(archive_speed, 2)
        ])

    # Тест распаковки
    extract_dir = EXTRACT_DIR / f"extract_{test_name.replace(' ', '_')}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    extract_start = time.time()
    extract_start_time = datetime.now().isoformat()
    subprocess.run(
        ['7z', 'x', f'-t{archive_type}', str(archive_path), f'-o{extract_dir}', '-y'],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    extract_end = time.time()
    extract_duration = extract_end - extract_start
    extract_speed = total_size / extract_duration if extract_duration > 0 else 0

    # Запись результатов распаковки в CSV
    with open(PERF_RESULTS, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            test_name,
            "Extract",
            total_size,
            file_count,
            extract_start_time,
            datetime.now().isoformat(),
            round(extract_duration, 3),
            round(extract_speed, 2)
        ])

    # Очистка
    if archive_path.exists():
        archive_path.unlink()
    shutil.rmtree(extract_dir, ignore_errors=True)

    return {
        "archive_time": archive_duration,
        "extract_time": extract_duration
    }


# Получаем тест-кейсы из конфига
test_cases = config.get('performance', {}).get('test_cases', [])


# Параметризованный тест производительности
@pytest.mark.parametrize("test_case", test_cases, ids=lambda tc: tc['name'])
def test_file_performance(make_files, init_csv_report, test_case):
    """Параметризованный тест производительности"""
    # Создаем файлы
    files = make_files(test_case['file_sizes'], prefix=test_case['name'])

    # Выполняем тест и записываем результаты
    results = run_performance_test(
        test_case['name'],
        files,
        test_case['total_size'],
        test_case['file_count']
    )

    # Для анализа внутри теста (необязательно)
    print(f"\nРезультаты для {test_case['name']}:")
    print(f"  Архивация: {results['archive_time']:.3f} сек")
    print(f"  Распаковка: {results['extract_time']:.3f} сек")


# -------------------- Анализ результатов --------------------

def analyze_performance_results():
    """Анализирует результаты производительности и выводит сравнение"""
    if not PERF_RESULTS.exists():
        print("Файл с результатами не найден")
        return

    results = {}
    with open(PERF_RESULTS, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_name = row['Test Case']
            operation = row['Operation']
            duration = float(row['Duration (s)'])

            if test_name not in results:
                results[test_name] = {}

            results[test_name][operation] = duration

    # Сравнение наборов файлов
    comparison_sets = [
        ("5 files × 2MB", "2 files × 5MB"),
        ("Single 1MB", "Single 10MB"),
        ("5 files × 2MB", "Single 10MB")
    ]

    print("\nСравнительная таблица производительности:")
    print("-" * 65)
    print(f"{'Тест':<20} | {'Операция':<10} | {'Время (сек)':<12} | {'Разница':<12}")
    print("-" * 65)

    for test_name, data in results.items():
        for operation, duration in data.items():
            print(f"{test_name:<20} | {operation:<10} | {duration:<12.3f} |")

    print("\nСравнение наборов файлов:")
    print("-" * 65)
    for set1, set2 in comparison_sets:
        if set1 in results and set2 in results:
            archive_diff = results[set2]['Archive'] - results[set1]['Archive']
            extract_diff = results[set2]['Extract'] - results[set1]['Extract']

            print(f"Сравнение: {set1} vs {set2}")
            print(
                f"  Архивация: {results[set1]['Archive']:.3f} сек vs {results[set2]['Archive']:.3f} сек ({archive_diff:+.3f} сек)")
            print(
                f"  Распаковка: {results[set1]['Extract']:.3f} сек vs {results[set2]['Extract']:.3f} сек ({extract_diff:+.3f} сек)")
            print("-" * 65)


# Фикстура для анализа результатов в конце сессии
@pytest.fixture(scope="session", autouse=True)
def final_analysis(request):
    """Анализирует результаты после всех тестов"""
    yield
    if any(item.nodeid for item in request.session.items if 'test_file_performance' in item.nodeid):
        analyze_performance_results()
