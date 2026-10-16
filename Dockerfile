FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=MSK-3
WORKDIR /app
# ffmpeg, шрифт с кириллицей и Pillow нужны только для сборки shorts по готовому плану.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pillow==12.3.0
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
