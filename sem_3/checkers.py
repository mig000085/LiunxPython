import os
import zlib
import re


def verify_extracted_files(extract_dir, source_dir, expected_files):
    """Проверка корректности извлеченных файлов"""
    errors = []
    source_dir_name = os.path.basename(source_dir)

    for file_path, expected_content in expected_files:
        full_path = os.path.join(extract_dir, source_dir_name, file_path)

        # Проверка существования файла
        if not os.path.exists(full_path):
            errors.append(f"Файл {file_path} не извлечен")
            continue

        # Проверка содержимого файла
        mode = 'rb' if isinstance(expected_content, bytes) else 'r'
        try:
            with open(full_path, mode) as f:
                actual_content = f.read()

                # Для текстовых файлов нормализуем строки
                if isinstance(expected_content, str):
                    actual_content = actual_content.replace('\r\n', '\n')
                    expected_content = expected_content.replace('\r\n', '\n')

                if actual_content != expected_content:
                    errors.append(
                        f"Содержимое {file_path} не совпадает\n"
                        f"Ожидалось: {expected_content!r}\n"
                        f"Получено: {actual_content!r}"
                    )
        except Exception as e:
            errors.append(f"Ошибка чтения файла {file_path}: {str(e)}")

    return len(errors) == 0, "\n".join(errors)


def verify_crc(process_output, file_path, content=None):
    """
    Проверка CRC32 из вывода 7z
    :param process_output: вывод команды 7z
    :param file_path: путь к проверяемому файлу
    :param content: содержимое файла (опционально)
    :return: кортеж (статус, сообщение)
    """
    match = re.search(r'\b([0-9A-Fa-f]{8})\b', process_output)
    if not match:
        return False, f"Не удалось найти CRC32 в выводе для файла {file_path}"

    crc_7z = match.group(1).upper()

    # Чтение содержимого файла, если не передано
    if content is None:
        with open(file_path, 'rb') as f:
            content = f.read()
    elif isinstance(content, str):
        content = content.encode('utf-8')

    calculated_crc = format(zlib.crc32(content) & 0xFFFFFFFF, '08X')

    if crc_7z != calculated_crc:
        return False, (
            f"CRC32 не совпадает для {file_path}: "
            f"7z={crc_7z}, calculated={calculated_crc}"
        )
    return True, ""


def verify_file_in_listing(output, filename):
    """Проверка наличия файла в листинге архива"""
    return filename in output