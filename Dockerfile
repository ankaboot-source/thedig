FROM python:3.13.0rc1-slim

# below is only required for PROD
# RUN apt-get update \
#    && apt-get upgrade -y \
#    && apt-get install -y --no-install-recommends curl git build-essential \
#    && apt-get autoremove -y \
#    && apt-get clean \
#    && rm -rf /var/apt/lists/* \
#    && rm -rf /var/cache/apt/*

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONDONTWRITEBYTECODE=True \
    PYTHONUNBUFFERED=True \
    PYTHONIOENCODING=utf-8

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME

COPY ./requirements.txt $APP_HOME/requirements.txt
# Install dependencies.
RUN pip install --no-cache-dir --upgrade -r $APP_HOME/requirements.txt

#COPY tests/ tests/
COPY gemway/ gemway/
COPY .env ./

COPY . $APP_HOME/

EXPOSE 8080

# Run the web service on container startup. Here we use uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--proxy-headers", "--use-colors", "--port", "8080"]
