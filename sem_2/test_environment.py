import os
import subprocess
import pytest
import shutil
import zlib
import tempfile
import re
from pathlib import Path

# Конфигурация путей
DATA_DIR = os.path.join(os.path.dirname(__file__), '../data')
TEST_DIR = os.path.join(DATA_DIR, 'test_dir')
ARCHIVE_FILE = os.path.join(DATA_DIR, 'test_archive.7z')
EXTRACT_DIR = os.path.join(DATA_DIR, 'extracted')

@pytest.fixture(scope="module")
def test_environment():
    """Фикстура для создания тестового окружения"""
    # Создаем тестовые данные
    os.makedirs(TEST_DIR, exist_ok=True)
    
    test_files = [
        ('file1.txt', 'Содержимое файла 1'),
        ('file2.txt', 'Содержимое файла 2'),
        ('binary.dat', b'\x00\x01\x02\x03\xFF'),
        ('subdir/file3.txt', 'Файл в поддиректории'),
        ('empty_file.txt', b'')
    ]
    
    for file_path, content in test_files:
        full_path = os.path.join(TEST_DIR, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        mode = 'wb' if isinstance(content, bytes) else 'w'
        with open(full_path, mode) as f:
            f.write(content)
    
    # Создаем архив
    subprocess.run(['7z', 'a', ARCHIVE_FILE, TEST_DIR], check=True)
    
    yield
    
    # Очистка после всех тестов
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
    if os.path.exists(ARCHIVE_FILE):
        os.remove(ARCHIVE_FILE)

def test_archive_listing(test_environment):
    """Тест команды вывода списка файлов в архиве (l)"""
    result = subprocess.run(
        ['7z', 'l', ARCHIVE_FILE],
        capture_output=True,
        text=True,
        check=True
    )
    
    expected_files = [
        'file1.txt',
        'file2.txt',
        'binary.dat',
        'subdir/file3.txt',
        'empty_file.txt'
    ]
    
    for file in expected_files:
        assert file in result.stdout, f"Файл {file} не найден в архиве"

def test_archive_extraction(test_environment):
    """Тест команды извлечения файлов (x)"""
    if os.path.exists(EXTRACT_DIR):
        shutil.rmtree(EXTRACT_DIR)
    os.makedirs(EXTRACT_DIR)
    
    subprocess.run(
        ['7z', 'x', ARCHIVE_FILE, f'-o{EXTRACT_DIR}', '-y'],
        check=True
    )
    
    extracted_files = [
        ('file1.txt', 'Содержимое файла 1'),
        ('file2.txt', 'Содержимое файла 2'),
        ('binary.dat', b'\x00\x01\x02\x03\xFF'),
        ('subdir/file3.txt', 'Файл в поддиректории'),
        ('empty_file.txt', b'')
    ]
    
    for file, expected_content in extracted_files:
        full_path = os.path.join(EXTRACT_DIR, os.path.basename(TEST_DIR), file)
        assert os.path.exists(full_path), f"Файл {file} не извлечен"
        
        mode = 'rb' if isinstance(expected_content, bytes) else 'r'
        with open(full_path, mode) as f:
            actual_content = f.read()
            assert actual_content == expected_content, (
                f"Содержимое {file} не совпадает\n"
                f"Ожидалось: {expected_content!r}\n"
                f"Получено: {actual_content!r}"
            )

def test_hash_calculation(test_environment):
    """Тест расчета хеш-сумм файлов"""
    test_files = [
        ('file1.txt', 'text'),
        ('binary.dat', 'binary'),
        ('empty_file.txt', 'empty')
    ]
    
    for file, file_type in test_files:
        test_file = os.path.join(TEST_DIR, file)
        
        try:
            result = subprocess.run(
                ['7z', 'h', '-scrcCRC32', test_file],
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            pytest.fail(f"Ошибка при расчете хеша для {file}: {e.stderr}")
        
        # Исправленный парсинг вывода 7z
        match = re.search(r'\b([0-9A-Fa-f]{8})\b', result.stdout)
        if not match:
            pytest.fail(f"Не удалось найти CRC32 в выводе для файла {file}")
        crc_7z = match.group(1).upper()
        
        # Вычисляем CRC32 напрямую
        with open(test_file, 'rb') as f:
            data = f.read()
            calculated_crc = format(zlib.crc32(data) & 0xFFFFFFFF, '08X')
        
        assert crc_7z == calculated_crc, (
            f"CRC32 не совпадает для {file} ({file_type}): "
            f"7z={crc_7z}, calculated={calculated_crc}"
        )

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
            
            # Исправленный парсинг вывода 7z
            match = re.search(r'\b([0-9A-Fa-f]{8})\b', result.stdout)
            if not match:
                pytest.fail("Не удалось найти CRC32 в выводе 7z")
            crc_7z = match.group(1).upper()
            
            expected_crc = format(zlib.crc32(content) & 0xFFFFFFFF, '08X')
            
            assert crc_7z == expected_crc, (
                f"Ошибка CRC32 для содержимого {content[:20]}: "
                f"7z={crc_7z}, ожидаемый={expected_crc}"
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)