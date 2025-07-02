import os
import subprocess
import shutil
import pytest
import yaml
import binascii
from datetime import datetime
from pathlib import Path


# Загрузка конфигурации
def load_config():
    with open('config.yaml', 'r') as f:
        return yaml.safe_load(f)


config = load_config()

# Пути
BASE_DIR = Path(__file__).parent.resolve()
PATHS = config.get('paths', {})
ARCHIVE_CONFIG = config.get('archive', {})

# Формирование путей
DATA_DIR = (BASE_DIR / PATHS.get('base_dir', '..') / PATHS.get('data_dir', 'data')).resolve()
TEST_DIR = DATA_DIR / PATHS.get('test_dir', 'test_dir')
ARCHIVE_FILE = DATA_DIR / (PATHS.get('archive_file', 'test_archive') + '.' + ARCHIVE_CONFIG.get('type', '7z'))
EXTRACT_DIR = DATA_DIR / PATHS.get('extract_dir', 'extracted')
PERF_ARCHIVE_DIR = DATA_DIR / PATHS.get('perf_archive_dir', 'perf_archives')

# Создание директорий
for directory in [DATA_DIR, TEST_DIR, EXTRACT_DIR, PERF_ARCHIVE_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


# Создаем тестовые данные на основе конфига
def create_test_files():
    """Создание тестовых файлов из конфигурации"""
    for file_info in config['test_files']:
        file_path = TEST_DIR / file_info['path']
        file_path.parent.mkdir(parents=True, exist_ok=True)

        content = file_info['content']
        file_type = file_info['type']

        # Преобразование содержимого в байты
        if file_type == 'binary':
            if content:  # Для непустых бинарных файлов
                content = binascii.unhexlify(content)
            else:  # Пустые бинарные файлы
                content = b''
        elif file_type == 'text':
            if isinstance(content, str):
                content = content.encode('utf-8')
            elif not content:  # Пустые текстовые файлы
                content = b''

        with open(file_path, 'wb') as f:
            f.write(content)


@pytest.fixture(autouse=True)
def log_statistics():
    """Фикстура для логирования статистики после каждого теста"""
    yield
    with open("stat.txt", "a") as stat_file:
        # Текущее время
        time_str = datetime.now().isoformat()

        # Количество файлов в тестовой директории
        file_count = 0
        if TEST_DIR.exists():
            for item in TEST_DIR.rglob('*'):
                if item.is_file():
                    file_count += 1

        # Размер архивного файла
        archive_size = ARCHIVE_FILE.stat().st_size if ARCHIVE_FILE.exists() else 0

        # Статистика загрузки CPU
        try:
            loadavg = Path('/proc/loadavg').read_text().strip()
        except Exception as e:
            loadavg = f"Error: {str(e)}"

        # Формируем строку статистики
        stat_line = f"{time_str}, {file_count}, {archive_size}, {loadavg}\n"
        stat_file.write(stat_line)


@pytest.fixture(scope="module")
def test_environment():
    """Фикстура для тестового окружения"""
    # Очистка перед запуском
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
    if ARCHIVE_FILE.exists():
        ARCHIVE_FILE.unlink()

    # Создаем тестовые файлы
    create_test_files()

    # Создаем архив
    archive_type = ARCHIVE_CONFIG.get('type', '7z')
    subprocess.run(
        ['7z', 'a', f'-t{archive_type}', str(ARCHIVE_FILE), str(TEST_DIR)],
        check=True
    )

    yield {
        'test_dir': TEST_DIR,
        'archive_file': ARCHIVE_FILE,
        'extract_dir': EXTRACT_DIR
    }

    # Очистка после тестов
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
    if ARCHIVE_FILE.exists():
        ARCHIVE_FILE.unlink()


# Фикстура для создания файлов разных размеров
@pytest.fixture(scope="function")
def make_files():
    """Фикстура для создания тестовых файлов разных размеров"""
    created_files = []

    def _make_files(sizes_mb, prefix="perf_file"):
        nonlocal created_files
        files = []
        block_size = config.get('performance', {}).get('block_size', '1M')

        for i, size in enumerate(sizes_mb):
            file_name = f"{prefix}_{i + 1}_{size}MB.dat"
            file_path = TEST_DIR / file_name

            # Создаем файл заданного размера
            subprocess.run(
                [
                    'dd',
                    'if=/dev/urandom',
                    f'of={file_path}',
                    f'bs={block_size}',
                    f'count={size}'
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            files.append(file_path)
            created_files.append(file_path)
        return files

    yield _make_files

    # Очистка созданных файлов
    for file_path in created_files:
        if file_path.exists():
            file_path.unlink()