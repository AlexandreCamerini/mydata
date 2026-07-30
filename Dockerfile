# Build do front e da API na mesma imagem: o FastAPI serve os dois, então o
# Railway roda um serviço só.

FROM node:24-alpine AS front
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requisitos.txt ./
RUN pip install --no-cache-dir -r requisitos.txt

COPY app/ ./app/
COPY --from=front /web/dist ./web/dist

# Sem estado em disco: o filesystem do container é efêmero e o bronze mora
# em tabela. Usuário sem privilégio por padrão.
RUN useradd --create-home --uid 10001 portal
USER portal

EXPOSE 8000
# $PORT é injetada pelo Railway; 8000 é só o padrão local.
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
