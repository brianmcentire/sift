# sift

> **Alpha software** — functional and in daily use across multiple machines, but expect rough edges and occasional breaking changes.

Distributed file inventory and deduplication across your LAN. Scanner agents on each machine hash files locally and send metadata to a central server. Use the CLI or web UI to find duplicates, verify backups, and browse your file inventory across all your hosts.

---

**Disclaimer:** sift is read-only with respect to the files it scans — it never writes, moves, modifies, renames, or deletes any file on the scanned host. The server does maintain its own database (`sift.duckdb`) on whatever machine it runs on, but that's the inventory, not your files. Reasonable efforts have been made to ensure this is actually true. That said, this is alpha software, and it comes with absolutely no warranty, no guarantee of fitness for any purpose, and no promise that your files will be any safer or better organized after using it. If it somehow causes data loss, existential dread, or unexpected charges from your cloud provider, that's on you. Use at your own risk.

---

## How It Works

- A lightweight **server** (FastAPI + DuckDB) runs centrally — on a NAS, home server, or any always-on machine
- **Agents** (`sift scan`) run on each machine you want to inventory: they walk the filesystem, SHA-256 hash each file, and POST metadata to the server over HTTP. Unchanged files are detected via mtime/size cache and skipped on subsequent scans, making rescans fast.
- The **CLI** (`sift ls`, `sift find`, `sift du`) queries the server to browse and search your inventory across all hosts
- The **web UI** (`sift server` then open browser) provides a visual tree browser with duplicate highlighting, filtering, and cross-host comparison

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

Then open `http://localhost:8765` in a browser for the web UI.

## Commands

### `sift scan [path]`

Walks the filesystem, hashes files, and sends metadata to the server. Shows live progress (files/s, MB/s, elapsed time). Uses a mtime/size cache so unchanged files are skipped on subsequent scans — rescans are much faster than initial scans.

```
sift scan /                     # scan everything from root
sift scan ~/Documents           # scan a specific directory
sift scan -x /                  # don't cross filesystem boundaries (skips mount points)
sift scan --quiet /             # suppress progress output
```

**Hard link awareness:** Files that share an inode (hard links) are detected and hashed only once. They appear with an orange tint in the web UI and are excluded from duplicate counts — hard links are the same physical file, not a true duplicate.

**Unraid:** On Unraid systems, `sift scan /` automatically skips individual `/mnt/disk*` paths and scans through `/mnt/user` instead, avoiding double-counting files that appear on multiple drives.

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

Start the API server. Also serves the web UI at `/`.

```
sift server                                        # localhost:8765
sift server --host 0.0.0.0 --port 8765            # accessible on LAN
sift server --db /path/to/sift.duckdb
```

## Web UI

Open `http://localhost:8765` (or your server address) after starting `sift server`.

### Features

- **Tree browser** — navigate your filesystem inventory with inline expand/collapse. Click a directory to expand it; click a file to see all copies of that file across all hosts.
- **Directory search** — type in the directory search box to expand the tree directly to matching directories, highlighted in blue. Non-matching ancestor directories are auto-expanded; matching dirs stay collapsed so you can open them at will. Hover any directory row to reveal a ⧉ button that copies its path to the clipboard.
- **Duplicate highlighting** — amber rows are duplicate files (same hash, multiple copies). Orange rows are hard-linked files (same inode, excluded from dup counts).
- **"Extra copies" on directories** — the hash column shows how many redundant file copies exist within a directory subtree. A directory with "3 extra copies" means 3 files could be removed while keeping one of each.
- **Cross-host host badges** — each file row shows which hosts it exists on, color-coded per host.
- **Search** — filename search (glob-style, `*` wildcards), hash search (prefix match), and directory name search (tree expansion to matches).
- **← Back navigation** — when viewing file copies or hash search results, a ← Back button returns to the tree view.
- **Filters** (all combinable):
  - **All files / Only dups** — toggle to show only duplicate rows and the directories that contain them
  - **Min dup size** — ignore duplicates below a size threshold (0 B, 1 KB, 1 MB, 100 MB, 1 GB, or custom with unit parsing)
  - **File type** — multi-select by category (images, video, audio, docs, code, archives, other)
  - **Host chips** — show/hide specific hosts from the merged view
- **Stats bar** — live counts of total files, total size, hosts, duplicate sets, and wasted space. Updates when min dup size or file type filters are applied; shows `(filtered)` when the dup stats reflect active filters rather than the full inventory.
- **Column toggle** — show/hide size, date, last seen, type, hash, and host columns.

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

- [x] React web UI
- [ ] `sift dups` — duplicate analysis (top wasted space, by category, host intersection/difference)
- [ ] `sift shell` — REPL with `cd`/`ls`/`find` against the inventory
- [ ] Windows agent testing
- [ ] `sift diff` — compare inventory between two hosts
