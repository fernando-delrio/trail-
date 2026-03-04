#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip

npm install
npm run build

pip install \
  flask \
  flask-sqlalchemy \
  flask-migrate \
  flask-swagger \
  psycopg2-binary \
  python-dotenv \
  flask-cors \
  gunicorn \
  "flask-admin==2.0.0" \
  typing-extensions \
  "flask-jwt-extended==4.6.0" \
  "wtforms==3.1.2" \
  sqlalchemy \
  colorama \
  cloudinary \
  requests

FLASK_APP=src/app.py flask db upgrade
