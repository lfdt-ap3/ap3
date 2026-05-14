FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install runtime deps (keep minimal; no build tools needed currently)
RUN pip install --no-cache-dir -U pip

# Copy repo source (build context should be repo root)
COPY pyproject.toml uv.lock README.md LICENSE /app/
COPY src/ /app/src/
COPY packages/ /app/packages/
COPY examples/ap3_playground/ /app/examples/ap3_playground/

# Install AP3 + functions + playground (editable keeps it simple for this repo layout)
RUN pip install --no-cache-dir "protobuf>=5.29.5,<6" && \
    pip install --no-cache-dir -e ".[a2a]" -e ./packages/ap3-functions -e ./examples/ap3_playground

EXPOSE 8088

ENV HOST=0.0.0.0 PORT=8088 RELOAD=false

CMD ["ap3-playground"]
