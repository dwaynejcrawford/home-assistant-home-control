FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3

COPY server.py /server.py
COPY www /www

CMD ["python3", "/server.py"]
