# Numbered screenshots of the dashboards

The screenshots shown on the admin page at `/admin/screenshots`. Each part of each dashboard page
has the number of the table its data comes from, and the table's box on the admin page's diagram has
the same number, so someone looking at the dashboard can find which table to update, and from there
which file to upload.

- **The numbers** are in `catalyst/admin/diagram.yaml` (`numbers`), one per table on the dashboards.
  A number stays with its table: give a new table the next number up.
- **The screenshots** (`*.webp`) and `screenshots.json` (what each number is on each one) are made by
  `take.mjs`. Don't edit them by hand.
- **What's numbered where** is the `SHOTS` list at the top of `take.mjs`: for each page, each part
  (by its CSS selector), what it is, and its table(s).

## Taking them again

Take them again when a panel is added, moved or renamed on the dashboard, or a table gets a number.
The tests fail if a table's number in `diagram.yaml` isn't the one on the screenshots, and the
screenshots page says they're out of date.

1. Publish the dashboards and start the admin page: `docker compose up -d`, then
   `docker compose run --rm publish`.
2. From the project's folder:

   ```bash
   node backend/catalyst/admin/screenshots/take.mjs
   ```

It needs Node.js 22 or later and a Chromium browser. By default it uses Playwright's
`chrome-headless-shell` in `~/.cache/ms-playwright/`; set `CHROME` to use another (e.g.
`CHROME=/usr/bin/chromium`). It logs in to the admin page as `admin` / `admin` (or `ADMIN_NAME` and
`ADMIN_PASSWORD`) to read the numbers.

On Ubuntu under WSL, the headless shell needs three libraries it doesn't come with, and the
dashboard's fonts (Segoe UI) are only on Windows. Without installing anything:

```bash
mkdir -p ~/shot-libs && cd ~/shot-libs
apt-get download libnspr4 libnss3 libasound2t64
for f in *.deb; do dpkg-deb -x "$f" root; done
mkdir -p fonts && cp /mnt/c/Windows/Fonts/segoeui*.ttf fonts/
cat > fonts.conf <<EOF
<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir>$HOME/shot-libs/fonts</dir></fontconfig>
EOF
cd -
LD_LIBRARY_PATH=~/shot-libs/root/usr/lib/x86_64-linux-gnu FONTCONFIG_FILE=~/shot-libs/fonts.conf \
  node backend/catalyst/admin/screenshots/take.mjs
```

It prints each screenshot as it's saved. It stops if something it's to number isn't on the page any
more (so the dashboard changed: update `SHOTS`), and it warns if `diagram.yaml` lists a table on a
page that isn't numbered on its screenshot.
