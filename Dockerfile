FROM python:3.12-bookworm
LABEL authors="Expliyh"
RUN export POETRY_HOME=/opt/poetry && curl -sSL https://install.python-poetry.org | python3 -
ADD . /workdir
WORKDIR /workdir
RUN /opt/poetry/bin/poetry install
ENV DATABASE_HOST=mariadb
ENV DATABASE_PORT=3306
ENV DATABASE_NAME=your_database_name
ENV DATABASE_USERNAME=your_username
ENV DATABASE_PASSWORD=your_password
ENV PIXIV_API_URL=""
ENV PIXIV_TOKEN=""
ENV TELEGRAM_BOT_TOKEN=your_telegram_token
ENV DEVELOPER_CHAT_ID=""
ENV DATABASE_PREFIX=""
ENV TZ=Asia/Shanghai
RUN mkdir /images
VOLUME /images
ENTRYPOINT ["python3", "main.py"]