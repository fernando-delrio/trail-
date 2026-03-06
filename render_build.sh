#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip

npm install
npm run build

pip install -r requirements.txt

FLASK_APP=src/app.py flask db upgrade
