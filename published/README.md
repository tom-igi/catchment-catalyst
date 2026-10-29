# Published dashboards

The public dashboards, written here by the publish step:

```bash
docker compose run --rm publish
```

There's a folder per location (e.g. `north-devon/`), holding everything its pages need, so
each can later be served at its own web address. `index.html` lists them all.

On your machine, see them at <http://localhost:8080>. Nothing here is kept in git: it can always
be made again from the database. The pages are written by `backend/catalyst/publish/`.
