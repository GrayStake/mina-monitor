FROM python:3.9.5-alpine

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

# Install Docker CLI
RUN apk update && apk add --no-cache docker-cli curl

RUN pip install docker requests six

WORKDIR /app
CMD ["python", "monitor.py"]