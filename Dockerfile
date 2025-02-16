FROM python:3.10

WORKDIR /app

COPY . /app/

RUN pip install --no-cache-dir -r requirements.txt

RUN pip install python-dotenv

CMD ["python", "mainlittle.py"]