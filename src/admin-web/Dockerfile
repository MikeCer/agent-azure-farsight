FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/tsconfig.json frontend/index.html ./
COPY frontend/src ./src
RUN npm install && npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY bff/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bff ./bff
COPY --from=frontend /src/frontend/dist ./bff/static
EXPOSE 8000
CMD ["uvicorn", "bff.main:app", "--host", "0.0.0.0", "--port", "8000"]
