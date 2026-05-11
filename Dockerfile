FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent data directory — mount a volume here to keep the DB across container restarts/updates
RUN mkdir -p /data
ENV ROTA_DB=/data/rota.db
VOLUME ["/data"]

EXPOSE 8080
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "app:app"]
