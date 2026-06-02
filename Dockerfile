# ── KWBot – Dockerfile ────────────────────────────────────────────────────
# Python 3.12 slim su Debian Bookworm (compatibile Windows/Linux/ARM)
FROM python:3.12-slim-bookworm

# Metadati
LABEL maintainer="KWBot"
LABEL description="KWB EasyFire EF2 – Modbus logger + Telegram bot"

# Variabili d'ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Rome

# Installa tzdata di sistema (per TZ) e pulisce cache apt
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Crea utente non-root per sicurezza
RUN useradd -m -u 1000 kwbot

# Directory di lavoro
WORKDIR /app

# Copia e installa le dipendenze PRIMA del codice (sfrutta la cache Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia il codice sorgente
COPY main.py .
COPY src/ ./src/

# La cartella /data è il volume esterno (DB, log, config.ini)
# Viene creata vuota qui; il volume la sovrascriverà a runtime
RUN mkdir -p /data && chown kwbot:kwbot /data

# Cambia utente
USER kwbot

# Healthcheck: verifica che il processo sia in esecuzione
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python main.py --status > /dev/null 2>&1 || exit 1

# Entry point
CMD ["python", "main.py"]
