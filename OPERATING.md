# Operating the dashboard

Just the essentials. For the details, see [README.md](README.md).

Run every command in a WSL terminal, in the project folder (`catchment-catalyst`).

---

## 1. Run it on your machine (dev)

```bash
docker compose up -d
```

Starts the database, the admin page and the dashboard. They keep running until you stop them.

The first time, and after getting new code, run these as well:

```bash
docker compose up -d --build
docker compose run --rm schema apply
```

The first builds the latest code. The second creates or updates the database tables (it asks
before changing anything).

To stop everything (the data is kept):

```bash
docker compose down
```

---

## 2. Run it on the live server

*To be added once the live server and its web address are set up.*

---

## 3. View the dashboard

- Dev: <http://localhost:8080>
- Live: *to be added*

It shows the data as it was when it was last published (see step 5).

---

## 4. View the tables in the database

- **Tables updated by Excel upload** (e.g. EA Scores): go to the admin page,
  <http://localhost:8000/admin> (login `admin` / `admin`), choose the table and click
  **Download as Excel**.
- **Every table:** connect a database client such as DBeaver: host `localhost`, port `5434`,
  database, user and password all `catalyst`.
- **What each table and column means:** open the data map:

  ```bash
  explorer.exe "$(wslpath -w datamap/site/index.html)"
  ```

---

## 5. Update the tables in the database

Most tables are updated in one of the two ways below; the data map (step 4) says which, under
"How it's filled". Locations are the exception, and are changed with the commands after that.

### Tables updated by Excel upload (e.g. EA Scores, Habitat & Land Use)

The admin page lists every one of them.

1. Go to <http://localhost:8000/admin> and log in.
2. Choose the table and click **Download as Excel**.
3. In Excel, add, change or delete rows. Keep the column names in row 1 as they are.
4. Upload the file, check the preview, and click **Approve**.

Each upload replaces the whole table, so always start from a fresh download.

### Tables filled from an outside source (e.g. Catchments, from the Environment Agency)

Each has its own import command, which downloads the data, shows what will change, and asks
before saving. For Catchments, add the catchment IDs to `imports/catchments.json`, then:

```bash
docker compose run --rm importer catchments imports/catchments.json
```

To see every import command:

```bash
docker compose run --rm importer --help
```

### Locations

To add a location, with the IDs of its catchments (put in your own name and IDs):

```bash
docker compose exec db psql -U catalyst -c "INSERT INTO locations (name, catchment_ids) VALUES ('North Devon', ARRAY['GB108050008080', 'GB108050008100'])"
```

To change a location's catchments (list all of them, not just the new ones):

```bash
docker compose exec db psql -U catalyst -c "UPDATE locations SET catchment_ids = ARRAY['GB108050008080', 'GB108050008100'] WHERE name = 'North Devon'"
```

### Then publish the dashboard

```bash
docker compose run --rm publish
```

Rebuilds the dashboard from the database. **The dashboard doesn't change until you run this.**

---

## 6. Add or remove an admin login

```bash
docker compose run --rm admin hash-password <name>
```

Asks for the person's password and prints a line for them. Put it in the `.env` file as
`ADMIN_USERS=<the line>`, separating people with commas. If there's no `.env` file yet, make
one first with `cp .env.example .env`. Then restart the admin page:

```bash
docker compose up -d
```

To remove someone, delete their entry from `ADMIN_USERS` and run `docker compose up -d` again.
Until `ADMIN_USERS` is set, the login is `admin` / `admin`.
