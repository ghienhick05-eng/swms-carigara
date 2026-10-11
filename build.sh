#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
# Never let the admin step block a deploy.
python manage.py create_menro_admin || echo "WARNING: create_menro_admin failed, continuing."