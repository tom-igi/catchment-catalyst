# To do

Agreed changes waiting to be built. Tom will say when to start each one.

- **Deploy the demo to the shared test VM,** at <https://rivers.smartbiosphere.com>, behind
  the VM's front door. Everything for it is ready: `docker-compose.front-door.yml` here, and
  `caddy/sites/rivers.caddy` in the [front-door](https://github.com/tom-igi/front-door) repo.
  **Deployed 12 November 2026** (data copied from the laptop, front door switched on).
  Waiting only for the DNS record: the address starts working as soon as it's there. Then
  check it (README.md step 10), set up the nightly backups and fill in OPERATING.md §2 and §3.
