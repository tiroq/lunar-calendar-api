FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY lunar_api ./lunar_api
COPY migrations ./migrations
COPY scripts ./scripts
RUN pip install --no-cache-dir ".[postgres]"
EXPOSE 8000
CMD ["uvicorn", "lunar_api.api:app", "--host", "0.0.0.0", "--port", "8000"]
