FROM python:3.12
LABEL authors="Expliyh"
#LABEL org.opencontainers.image.source = "https://github.com/expliyh/py-acgimg-bot"
ADD . /workdir
WORKDIR /workdir
RUN pip install -r requirements.txt
ENV DATABASE_HOST=mariadb
ENV DATABASE_PORT=3306
ENV DATABASE_NAME=your_database_name
ENV DATABASE_USERNAME=your_username
ENV DATABASE_PASSWORD=your_password
ENV DATABASE_PREFIX=""
ENV TZ=Asia/Shanghai
RUN mkdir /images
VOLUME /images
ENTRYPOINT ["python3", "run", "uvicorn", "main:app", "--host", "0.0.0.0"]