FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 1000 cutcraft && useradd --uid 1000 --gid cutcraft --create-home cutcraft \
    && mkdir /app/output && chown cutcraft:cutcraft /app/output
COPY *.py ./
COPY prompts/ prompts/
COPY schemas/ schemas/
COPY examples/ examples/
COPY data/ data/
COPY scripts/ scripts/
COPY tests/ tests/
COPY docs/ docs/
ENTRYPOINT ["python", "scripts/container_entrypoint.py"]
CMD ["python", "main.py", "--demo"]
