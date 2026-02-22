# sift

> **Alpha software** — functional and in daily use across multiple machines, but expect rough edges and occasional breaking changes.

Distributed file inventory and deduplication across your LAN. Scanner agents on each machine hash files locally and send metadata to a central server. Use the CLI to find duplicates, verify backups, and browse your file inventory across all your hosts.

---

**Disclaimer:** sift is read-only with respect to the files it scans — it never writes, moves, modifies, renames, or deletes any file on the scanned host. The server does maintain its own database (`sift.duckdb`) on whatever machine it runs on, but that's the inventory, not your files. Reasonable efforts have been made to ensure this is actually true. That said, this is alpha software written by humans, and it comes with absolutely no warranty, no guarantee of fitness for any purpose, and no promise that your files will be any safer or better organized after using it. If it somehow causes data loss, existential dread, or unexpected charges from your cloud provider, that's on you. Use at your own risk.

---

## How It Works

- A lightweight **server** (FastAPI + DuckDB) runs centrally — on a NAS, home server, or any always-on machine
- **Agents** (`sift scan`) run on each machine you want to inventory: they walk the filesystem, SHA-256 hash each file, and POST metadata to the server over HTTP. Unchanged files are detected via mtime/size cache and skipped on subsequent scans, making rescans fast.
- The **CLI** (`sift ls`, `sift find`, `sift du`) queries the server to browse and search your inventory across all hosts

## Installation

### Server

**Docker (recommended):**

```bash
# Build the image (from Apple Silicon Mac targeting x86_64 server):
docker build --platform linux/amd64 -t sift-server .

# On x86_64 natively:
docker build -t sift-server .

docker compose up -d
```

Example `docker-compose.yml`:

```yaml
services:
  sift:
    image: sift-server
    container_name: sift
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - /path/to/appdata/sift:/data
    environment:
      - SIFT_DB_PATH=/data/sift.duckdb
      - SIFT_CONFIG_PATH=/data/sift.config
```

**Direct (no Docker):**

```bash
pip install -e ".[server]"
sift server --host 0.0.0.0 --port 8765 --db /path/to/sift.duckdb
```

To ship a Docker image to a remote server without a registry:

```bash
docker save sift-server | gzip > sift-server.tar.gz
scp sift-server.tar.gz user@server:/tmp/

# On the server:
docker load < /tmp/sift-server.tar.gz
docker compose up -d
```

### Agent / CLI

Install on each machine you want to scan or query from.

**Standard (Mac, most Linux):**

```bash
pip install -e .
```

**Raspberry Pi OS / Debian Bookworm and newer** (PEP 668 externally-managed environments):

```bash
sudo apt install pipx
pipx install -e ~/path/to/sift
pipx ensurepath
```

**Unraid or other locked-down systems — standalone binary:**

```bash
make dist-agent              # builds dist/sift-linux-amd64
scp dist/sift-linux-amd64 root@unraid:/usr/local/bin/sift
```

Requires Docker on your build machine. Produces a self-contained binary with no Python dependency on the target — works on any Linux x86_64 system with glibc 2.14+, which covers anything from the last decade.

### Point agents at the server

Create `~/.sift.config` on each agent machine:

```toml
[server]
url = "http://my-server:8765"
```

Or set `SIFT_SERVER=http://my-server:8765` as an environment variable.

## Quick Start

```bash
sift server &                           # start the server locally (or use Docker)
sift scan ~/Documents                   # scan a directory
sift ls -lh ~/Documents                 # browse with sizes
sift find / -name "*.pdf" -duplicates   # find duplicate PDFs
sift du -h --by-category ~             # disk usage by file type
sift status                             # overview of all hosts
```

## Commands

### `sift scan [path]`

Walks the filesystem, hashes files, and sends metadata to the server. Shows live progress including files/s, MB/s, percent complete, and estimated time remaining. Uses a mtime/size cache so unchanged files are skipped on subsequent scans — rescans are much faster than initial scans.

```
sift scan /                     # scan everything from root
sift scan ~/Documents           # scan a specific directory
sift scan -x /                  # don't cross filesystem boundaries (skips mount points)
sift scan --quiet /             # suppress progress output
```

### `sift ls [path]`

Browse the inventory like a filesystem. Defaults to current directory.

```
sift ls
sift ls -l ~/Documents          # long format (permissions, size, date, hash)
sift ls -lh ~/Documents         # human-readable sizes
sift ls -lS ~/Documents         # sort by size
sift ls -lR ~/Documents         # recursive
sift ls -lt ~/Documents         # sort by modification time
sift ls --duplicates ~/         # show only files that exist on other hosts
sift ls --full-hash ./file.txt  # show full 64-char SHA-256 hash
sift ls --host unraid /mnt/user # query a specific host
sift ls --all-hosts /           # show files from all hosts combined
```

### `sift find [path] [filters]`

Search the inventory. Defaults to current directory.

```
sift find / -name "*.pdf"
sift find / -iname "*.jpg"           # case-insensitive
sift find / -size +1G                # larger than 1GB
sift find / -size -100M              # smaller than 100MB
sift find / -mtime -7                # modified in last 7 days
sift find / -mtime +365              # not modified in over a year
sift find / -ext nef                 # by extension
sift find / -category video          # by file category
sift find / -hash <sha256>           # find all copies of a file by hash
sift find / -duplicates              # files that exist on more than one host
sift find / -ls                      # long format output
sift find / --host unraid -size +1G
sift find / --all-hosts -duplicates
```

### `sift du [path]`

Disk usage summary. Defaults to current directory.

```
sift du -h ~/Documents
sift du -h -d 2 ~/Documents          # show 2 levels deep
sift du -h -s ~/Documents            # total only
sift du -h --by-category ~           # breakdown by file type
sift du --duplicates-only -h ~       # only count duplicate files
sift du --all-hosts /
sift du --host unraid /mnt/user
```

### `sift status`

Server overview: all known hosts, last scan time, file counts, and duplicate statistics.

### `sift server`

Start the API server.

```
sift server                                        # localhost:8765
sift server --host 0.0.0.0 --port 8765            # accessible on LAN
sift server --db /path/to/sift.duckdb
```

## Configuration

Config file: `~/.sift.config` (TOML). All fields are optional — reasonable defaults apply.

```toml
[server]
url = "http://localhost:8765"     # where the API server lives

[agent]
volatile_mtime_threshold_days = 30   # skip hashing recently-modified VM disks, mail DBs, etc.
upsert_batch_size = 500
seen_batch_size = 5000

[cli]
# host = "my-machine"   # override default hostname for queries
```

Environment variables take precedence over the config file:

| Variable | Purpose |
|---|---|
| `SIFT_SERVER` | Server URL |
| `SIFT_HOST` | Hostname override for CLI queries |
| `SIFT_DB_PATH` | Path to `sift.duckdb` (server) |
| `SIFT_CONFIG_PATH` | Path to config file |

## Building a Standalone Agent Binary

For systems where installing Python packages isn't an option:

```bash
make dist-agent
```

Requires Docker. Produces `dist/sift-linux-amd64`. Copy it to the target machine and run it directly — no Python, pip, or anything else required.

## Contributing

This is a personal project shared for the community's use. Issues and PRs may not receive responses. Feedback is welcome; please don't expect timely replies or merges.

## Roadmap

- [ ] React web UI
- [ ] `sift dups` — duplicate analysis (top wasted space, by category, host intersection/difference)
- [ ] `sift shell` — REPL with `cd`/`ls`/`find` against the inventory
- [ ] Windows agent testing
- [ ] `sift diff` — compare inventory between two hosts
