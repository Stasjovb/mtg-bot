# The Forgetful Fish website with its production server (waitress).
# Build:  docker build -t fish-website .
# Run:    docker run -p 8080:8080 -v fish-data:/data fish-website
# See ONLINE.md for the settings a real deployment needs.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    MTG_BOT_HOST=0.0.0.0 \
    PORT=8080 \
    MTG_BOT_CARD_POOL=fish \
    MTG_BOT_FEEDBACK_DIR=/data/feedback \
    MTG_BOT_REPLAYS_ROOT=/data/replays

WORKDIR /app

COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY src ./src
COPY data ./data

# A non-root user. The website writes card images into data/card_images and
# feedback and replays into /data, so those must belong to it.
RUN useradd --create-home --uid 10001 fish \
    && mkdir -p /data/feedback /data/replays \
    && chown -R fish /app/data /data
USER fish

VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "-m", "mtg_bot.web_server"]
