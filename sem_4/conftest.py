import pytest
import yaml
import paramiko
import os
import binascii
import tempfile
import stat
import csv
import re
from pathlib import Path
from datetime import datetime

# Загрузка конфигурации
with open('config.yaml') as f:
    config = yaml.safe_load(f)

# Пути из конфигурации
DATA_DIR = Path(config.get('paths', {}).get('data_dir', 'data'))
TEST_DIR = Path(config.get('paths', {}).get('test_dir', '/home/mig/test_files'))
EXTRACT_DIR = Path(config.get('paths', {}).get('extract_dir', '/home/mig/extracted'))
ARCHIVE_FILE = config.get('archive', {}).get('file', '/home/mig/test_archive.7z')
PERF_ARCHIVE_DIR = Path(config.get('paths', {}).get('perf_archive_dir', '/home/mig/perf_archives'))


class SSHClient:
    def __init__(self, ssh_client):
        self.client = ssh_client

    def run_ssh_command(self, command, check=True):
        """Выполняет команду на удаленном сервере через SSH"""
        stdin, stdout, stderr = self.client.exec_command(command)
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()

        if check and exit_status != 0:
            raise Exception(f"SSH command failed ({exit_status}): {command}\n{error}")
        return output

    def download_file(self, remote_path, local_path):
        """Скачивает файл с сервера"""
        sftp = self.client.open_sftp()
        sftp.get(remote_path, local_path)
        sftp.close()

    def upload_file(self, local_path, remote_path):
        """Загружает файл на сервер"""
        sftp = self.client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()

    def download_directory(self, remote_path, local_path):
        """Рекурсивное скачивание директории"""
        sftp = self.client.open_sftp()

        if not os.path.exists(local_path):
            os.makedirs(local_path)

        for item in sftp.listdir(remote_path):
            remote_item = f"{remote_path}/{item}"
            local_item = os.path.join(local_path, item)

            if stat.S_ISDIR(sftp.stat(remote_item).st_mode):
                self.download_directory(remote_item, local_item)
            else:
                sftp.get(remote_item, local_item)

        sftp.close()

    def close(self):
        self.client.close()


@pytest.fixture(scope="session")
def ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh_config = config.get('ssh', {})
    connect_params = {
        'hostname': ssh_config.get('host', 'localhost'),
        'port': ssh_config.get('port', 22),
        'username': ssh_config.get('user', 'user'),
        'password': ssh_config.get('passwd', ''),
        'key_filename': ssh_config.get('keyfile', None),
        'timeout': 10
    }

    try:
        client.connect(**connect_params)
        yield SSHClient(client)
    except Exception as e:
        pytest.fail(f"SSH connection failed: {str(e)}")
    finally:
        client.close()


@pytest.fixture(scope="session")
def test_environment(ssh_client):
    """Подготовка тестового окружения на удаленном сервере"""
    # Устанавливаем sysstat для мониторинга CPU
    ssh_client.run_ssh_command("command -v mpstat || sudo apt-get install -y sysstat", check=False)

    # Создаем директории
    ssh_client.run_ssh_command(f"mkdir -p {TEST_DIR}")
    ssh_client.run_ssh_command(f"mkdir -p {EXTRACT_DIR}")
    ssh_client.run_ssh_command(f"mkdir -p {PERF_ARCHIVE_DIR}")

    # Создаем тестовые файлы
    for file_info in config['test_files']:
        remote_path = f"{TEST_DIR}/{file_info['path']}"
        remote_dir = os.path.dirname(remote_path)

        # Создаем директорию, если нужно
        ssh_client.run_ssh_command(f"mkdir -p {remote_dir}", check=False)

        # Подготовка содержимого файла
        content = file_info['content']
        file_type = file_info['type']

        if file_type == 'binary' and content:
            content = binascii.unhexlify(content)
        elif file_type == 'text' and content:
            content = content.encode('utf-8')
        else:
            content = b''

        # Создаем временный файл
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        # Копируем файл на сервер
        ssh_client.upload_file(tmp_path, remote_path)

        # Удаляем временный файл
        os.unlink(tmp_path)

    # Создаем архив для тестов
    archive_type = config.get('archive', {}).get('type', '7z')
    ssh_client.run_ssh_command(
        f"7z a -t{archive_type} {ARCHIVE_FILE} {TEST_DIR}/*"
    )

    yield

    # Очистка после тестов
    ssh_client.run_ssh_command(f"rm -rf {TEST_DIR}/*", check=False)
    ssh_client.run_ssh_command(f"rm -rf {EXTRACT_DIR}/*", check=False)
    ssh_client.run_ssh_command(f"rm -rf {PERF_ARCHIVE_DIR}/*", check=False)
    ssh_client.run_ssh_command(f"rm -f {ARCHIVE_FILE}", check=False)


@pytest.fixture
def make_files(ssh_client):
    """Фикстура для создания тестовых файлов производительности"""

    def _make_files(file_sizes, prefix="test"):
        files = []
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        # Очищаем имя префикса от пробелов и спецсимволов
        safe_prefix = re.sub(r'[^a-zA-Z0-9_]', '_', prefix)

        for i, size in enumerate(file_sizes):
            # Размер может быть в MB или count
            if isinstance(size, str) and size.endswith('MB'):
                size_mb = int(size.replace('MB', ''))
                size_bytes = size_mb * 1024 * 1024
            else:
                size_bytes = size

            # Создаем файл
            filename = f"{safe_prefix}_{timestamp}_{i}.dat"
            remote_path = f"{TEST_DIR}/{filename}"

            # Экранируем путь и создаем файл нужного размера
            ssh_client.run_ssh_command(
                f"dd if=/dev/urandom of='{remote_path}' bs=1024 count={size_bytes // 1024}"
            )

            files.append(remote_path)

        return files

    return _make_files


@pytest.fixture(scope="session", autouse=True)
def init_csv_report():
    """Инициализация CSV-файла для результатов производительности"""
    PERF_RESULTS = Path("performance_results.csv")

    if PERF_RESULTS.exists():
        backup_name = f"performance_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        PERF_RESULTS.rename(backup_name)

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
            "Speed (MB/s)",
            "Max CPU (%)"  # Новая колонка
        ])

    # Создаем директорию для логов CPU
    os.makedirs("cpu_logs", exist_ok=True)

    return PERF_RESULTS