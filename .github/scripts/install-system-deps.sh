#!/usr/bin/env bash

sudo apt-get update
sudo apt-get install -y \
  build-essential \
  libmariadb-dev \
  libssl-dev \
  pkg-config

"$(dirname "$0")/update-poetry.sh"
