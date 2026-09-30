FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir "typesafe-sdk>=0.7.2" "pydantic>=2" "fastapi>=0.110" "uvicorn>=0.27"
COPY src/ ./src/
COPY fixtures/ ./fixtures/
COPY scripts/ ./scripts/
ENV JEV_MODE=mock ROUTER_DRY_RUN=true
EXPOSE 8000
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
