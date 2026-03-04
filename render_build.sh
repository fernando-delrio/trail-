#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip
pip install pipenv

npm install
npm run build

pipenv install --deploy
pipenv run flask db upgrade
