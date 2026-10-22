FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml LICENSE.md ./
COPY agentic_dt/ ./agentic_dt/
COPY agents/*.md ./agents/
COPY exercises/*.md ./exercises/
COPY config/project.yaml ./config/project.yaml
COPY extensions/web/ ./extensions/web/
RUN mkdir -p docs && printf '%s\n' 'Deployment scaffold. Each tester supplies an independent project brief.' > docs/brief.md
RUN pip install --no-cache-dir . -r extensions/web/requirements.txt
RUN useradd --uid 10001 --create-home web && mkdir /data && chown web:web /data
ENV WEB_DATA_ROOT=/data PYTHONUNBUFFERED=1 WEB_COOKIE_SECURE=1
USER web
VOLUME ["/data"]
EXPOSE 8787
CMD ["gunicorn", "--bind", "0.0.0.0:8787", "--workers", "2", "--threads", "4", "--timeout", "60", "extensions.web.app:create_app()"]
