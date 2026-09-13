#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Home Control..."
exec python3 /server.py
