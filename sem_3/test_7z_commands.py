import os
import subprocess
import pytest
import shutil
import tempfile
import binascii
from pathlib import Path
from checkers import verify_extracted_files, verify_crc, verify_file_in_listing
from conftest import DATA_DIR, TEST_DIR, ARCHIVE_FILE, EXTRACT_DIR, config

# Подготовка ожидаемых файлов
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

def test_archive_listing(test_environment):
    """Тест команды вывода списка файлов в архиве (l)"""
    result = subprocess.run(
        ['7z', 'l', str(ARCHIVE_FILE)],
        capture_output=True,
        text=True,
        check=True
    )
    
    for file_info in config['test_files']:
        assert verify_file_in_listing(result.stdout, file_info['path']), \
            f"Файл {file_info['path']} не найден в архиве"

def test_archive_extraction(test_environment):
    """Тест команды извлечения файлов (x)"""
    if EXTRACT_DIR.exists():
        shutil.rmtree(EXTRACT_DIR)
    EXTRACT_DIR.mkdir(parents=True)
    
    subprocess.run(
        ['7z', 'x', str(ARCHIVE_FILE), f'-o{EXTRACT_DIR}', '-y'],
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