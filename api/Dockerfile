FROM python:3.12-slim

# Build-time version stamp: docker build --build-arg APP_VERSION=2.0 ...
ARG APP_VERSION=1.0
ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 5000
# access log goes to stdout => visible with kubectl logs
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "app:app"]
