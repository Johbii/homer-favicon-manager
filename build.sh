#!/usr/bin/env sh
sudo docker compose down --remove-orphans && sudo docker compose build && sudo docker compose up --force-recreate
