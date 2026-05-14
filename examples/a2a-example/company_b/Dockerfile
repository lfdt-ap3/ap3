FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY . /app

WORKDIR /app/examples/a2a-example/company_b
RUN uv sync --frozen

ARG PORT=10003
EXPOSE ${PORT}
CMD ["uv", "run", "."]
