FROM python:3.10-slim

WORKDIR /app

# system deps for matplotlib + fonts (paper-friendly)
RUN apt-get update && apt-get install -y \
    build-essential \
    fontconfig \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

CMD ["python", "--version"]
