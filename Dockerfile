FROM python:3.11-slim

WORKDIR /app

# Use Tsinghua apt mirror
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources
# Install uv via pip (Tsinghua PyPI mirror)
RUN pip install uv -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY pyproject.toml .
COPY src/ src/
COPY ip2region.xdb .

# Install dependencies via uv (Tsinghua PyPI mirror)
RUN uv sync --no-dev --index-url https://pypi.tuna.tsinghua.edu.cn/simple

CMD ["/app/.venv/bin/python", "src/main.py"]
