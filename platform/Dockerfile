FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VAIO_DATABASE=/app/data/panel.sqlite
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home vaio
COPY vaio vaio
COPY agent agent
COPY vendor vendor
COPY web web
COPY scripts scripts
RUN mkdir -p /app/data && chown -R vaio:vaio /app/data
USER vaio
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "vaio.server:create_app()"]
