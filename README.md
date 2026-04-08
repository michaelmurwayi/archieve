# Archiver System

## Overview
The Archiver System archives files and folders from users belonging to a specified Linux group, stores archive metadata in PostgreSQL, exposes the data via a Django REST API, and provides a dashboard for viewing archived records.

## Components
- Archiver Script (CLI)
- Django REST API
- PostgreSQL Database
- Dashboard Frontend
- Docker Compose Environment

## Features
- Archives all files and folders in user home directories
- Handles hidden files and nested directories
- Logs success/failure in PostgreSQL
- REST API for archived records
- Dashboard for viewing archive activity
- Debian package support

## Tech Stack
- Python
- Django + Django REST Framework
- PostgreSQL
- Docker / Docker Compose
- React (Dashboard)

## Run with Docker
```bash
sudo docker compose up --build -d

Run Migrations
sudo docker compose exec api python manage.py makemigrations archive_api
sudo docker compose exec api python manage.py migrate

Run API
http://localhost:8000/api/archived-files/

Build Debian Package
dpkg-deb --build package/archiver_1.0.0
