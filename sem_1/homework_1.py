# Задание 1.
#
# Условие:
# Написать функцию на Python, которой передаются в качестве параметров команда и текст.
# Функция должна возвращать True, если команда успешно выполнена и текст
# найден в её выводе и False в противном случае.
# Передаваться должна только одна строка, разбиение вывода использовать не нужно.

import subprocess


def check_command_output(command, text):
    process = subprocess.run(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    return process.returncode == 0 and text in process.stdout


# Проверяем вывод команды echo 'Hello, World!' на наличие подстроки "Hello"
print(check_command_output("echo 'Hello, World!'", "Hello"))  # Вернёт True
