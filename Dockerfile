FROM python:3.11.2-alpine3.17

WORKDIR /usr/src/app

ENV GID 1000
ENV UID 1000
ENV DAEMON_ENABLED 1
ENV VERIFY_SSL 1
ENV DEBUG 0

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

USER ${UID}:${GID}
CMD python -u ./app.py --config=/www/assets/source/config.yml --workdir=/www/assets/managed --output=/www --daemon=${DAEMON_ENABLED} --verify-ssl=${VERIFY_SSL} --debug=${DEBUG}
