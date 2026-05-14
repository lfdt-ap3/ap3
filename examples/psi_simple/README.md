# AP3 - PSI simple example

This example shows how to use AP3 to perform a privacy-preserving sanction check using Private Set Intersection (PSI).

## Prerequisites

- Python `>=3.11` and [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Docker + Docker Compose (for the Docker path)

---

## Run it (Docker)

From this folder:

```bash
docker compose up --build
```

The receiver and initiator come up together; the initiator runs once against the default customer (which is in the sanction list) and prints the signed result. Override the customer with `command:` in `docker-compose.yml` or by re-running the initiator service:

```bash
docker compose run --rm initiator uv run --package psi-simple python examples/psi_simple/initiator.py \
  --port 10002 --host 0.0.0.0 --public-url http://initiator:10002 \
  --receiver http://receiver:10003 \
  --customer "Alice Nobody,X0000000,1 Nowhere St"
```

## Run it (local Python)

Install dependencies in the repo root (skip if already done)

```
uv sync
```

In two terminals, from the repo root:

``` bash
# terminal 1
source .venv/bin/activate
cd examples/psi_simple
uv run receiver.py

# terminal 2
source .venv/bin/activate
cd examples/psi_simple
uv run initiator.py --customer "Joe Quimby,S4928374,213 Church St"
```

The default customer is in the receiver's sanction list — expect a match. 

Try a name not in the list to see a no-match result:

```bash
uv run initiator.py --customer "Alice Nobody,X0000000,1 Nowhere St"
```

## Data (SQLite)

The receiver loads its sanction list from a small SQLite database:

- DB path: `data/receiver.db`
- Table: `sanction_entries(row TEXT)`

The DB is auto-created and seeded on first run.

### Editing the data

From the example folder (example/psi_simple):

List rows:

```bash
sqlite3 data/receiver.db "select id, row from sanction_entries order by id;"
```

Insert a row:

```bash
sqlite3 data/receiver.db "insert or ignore into sanction_entries(row) values ('Alice Nobody,X0000000,1 Nowhere St');"
```

Delete a row by id:

```bash
sqlite3 data/receiver.db "delete from sanction_entries where id = 1;"
```
