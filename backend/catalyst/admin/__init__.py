"""The admin page: log in, then download a table as Excel, edit it and upload it again.

- app.py        the web pages
- passwords.py  who can log in (the ADMIN_USERS setting)
- settings.py   the settings it needs, from environment variables
- uploads.py    the uploads table and the uploaded files
- templates/    the pages' HTML

Started by `python -m catalyst.admin serve` (the `admin` service in Docker Compose).
"""
