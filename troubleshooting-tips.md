# Sift — Tips & Debugging

## Debug Query Endpoint

`GET /debug/query?sql=...` runs a read-only SQL query against the live DuckDB database.
Only `SELECT` and `WITH` statements are allowed.

```bash
# Basic usage
curl -sG 'http://localhost:8765/debug/query' \
  --data-urlencode "sql=SELECT COUNT(*) FROM files" \
  | python3 -m json.tool

# Per-host file count and total size
curl -sG 'http://localhost:8765/debug/query' \
  --data-urlencode "sql=SELECT host, COUNT(*) AS files, SUM(size_bytes)/1024/1024/1024 AS gb FROM files GROUP BY host" \
  | python3 -m json.tool

# Verify dup counts for a host
curl -sG 'http://localhost:8765/debug/query' \
  --data-urlencode "sql=SELECT COUNT(*) FROM files f INNER JOIN host_hash_stats hhs ON hhs.host = f.host AND hhs.hash = f.hash WHERE f.host = 'Unraid' AND hhs.copy_count_effective > 1" \
  | python3 -m json.tool

# Check aggregate table freshness
curl -sG 'http://localhost:8765/debug/query' \
  --data-urlencode "sql=SELECT * FROM aggregate_meta" \
  | python3 -m json.tool

# Top 10 largest duplicate sets by wasted space
curl -sG 'http://localhost:8765/debug/query' \
  --data-urlencode "sql=SELECT hash, copy_count, host_count, size_bytes/1024/1024 AS mb, wasted_bytes/1024/1024 AS wasted_mb FROM hash_stats ORDER BY wasted_bytes DESC LIMIT 10" \
  | python3 -m json.tool
```

### Why not use the DuckDB CLI directly?

DuckDB doesn't support concurrent access — even `-readonly` mode fails if the server
is holding the database open. The debug endpoint routes queries through the running
server's connection.
