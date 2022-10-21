FROM python:3.10-slim-buster

RUN apt-get update -y && apt-get upgrade -y
RUN /usr/local/bin/python -m pip install --upgrade pip

RUN mkdir -p /opt/app
WORKDIR /opt/app
COPY ./requirements.txt /opt/app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /opt/app
