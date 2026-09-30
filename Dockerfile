FROM python:3.12-slim
WORKDIR /app
# Install from pyproject so the image cannot drift from the declared deps.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY fixtures/ ./fixtures/
COPY scripts/ ./scripts/
ENV JEV_MODE=mock ROUTER_DRY_RUN=true
EXPOSE 8000
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
