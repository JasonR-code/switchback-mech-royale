FROM buildpack-deps:bookworm@sha256:cba7fa3c133e3110d747518182a10a8f969691e6788abea5f454ce7f83de1542 AS toolchain
FROM python:3.13.18-slim-bookworm@sha256:f3dac913ab53b78c64f26d5518fcd7043d5a1a46522d6a493b598c3ed12f62a6 AS runtime

FROM runtime AS build
RUN --mount=from=toolchain,source=/usr,target=/usr \
    --mount=type=bind,source=geometry.cpp,target=/tmp/geometry.cpp \
    g++ -std=c++17 -O3 -fPIC -shared /tmp/geometry.cpp -o /geometry.so

FROM runtime
WORKDIR /bot
COPY --from=build --chmod=0555 /geometry.so .
COPY --chmod=0444 *.py defaults.json ./
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
RUN python3 -c "import ctypes; ctypes.CDLL('/bot/geometry.so')"
ENTRYPOINT ["python3", "-u", "/bot/main.py"]
