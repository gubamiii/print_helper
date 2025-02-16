# Используем официальный образ Python 3.10
FROM python:3.10

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файлы проекта в контейнер
COPY . /app/

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Загружаем переменные окружения (если используем dotenv)
RUN pip install python-dotenv

# Запуск бота
CMD ["python", "mainlittle.py"]