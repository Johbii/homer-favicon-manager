FROM python:3.11.2-alpine3.17

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

WORKDIR /usr/src/app
COPY . /usr/src/app

RUN adduser -u 5678 --disabled-password --gecos "" appuser \
    && chown -R appuser /usr/src/app
USER appuser

ENV DAEMON_ENABLED 1
ENV VERIFY_SSL 1
ENV DEBUG 0

CMD python app.py \
    --config=/data/source/config.yml \
    --workdir=/data/managed \
    --output=/data \
    --daemon=${DAEMON_ENABLED} \
    --verify-ssl=${VERIFY_SSL} \
    --debug=${DEBUG}
