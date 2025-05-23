# Задание 2. (повышенной сложности)
#
# Доработать функцию из предыдущего задания таким образом, чтобы
# у неё появился дополнительный режим работы,
# в котором вывод разбивается на слова с удалением всех знаков пунктуации
# (их можно взять из списка string.punctuation модуля string).
# В этом режиме должно проверяться наличие слова в выводе.


import subprocess
import string


def check_command_output(command, text, word_mode=False):
    # Выполняем команду в shell
    process = subprocess.run(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        text=True,
    )

    # Если команда завершилась с ошибкой, возвращаем False
    if process.returncode != 0:
        return False

    # Режим проверки слов
    if word_mode:
        # Создаем таблицу замены пунктуации на пробелы
        translator = str.maketrans(string.punctuation, " " * len(string.punctuation))
        # Удаляем пунктуацию и разбиваем вывод на слова
        cleaned_output = process.stdout.translate(translator)
        words = cleaned_output.split()
        # Проверяем наличие слова в списке
        return text in words

    # Стандартный режим проверки подстроки
    return text in process.stdout


print(check_command_output("echo 'Hello, World!'", "World", word_mode=True))
print(check_command_output("echo 'text.txt'", "txt", word_mode=True))
