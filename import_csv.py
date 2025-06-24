#!/usr/bin/env python3
"""
Import historical DHT22 CSV data into InfluxDB 1.x in robust batches,
cleaning null bytes on the fly.
"""
import csv
import logging
from typing import Iterator, List, Dict
from influxdb import InfluxDBClient, exceptions

# ── CONFIG ─────────────────────────────────────────────
INFLUX_HOST     = "<your_influxdb_host>"
INFLUX_PORT     = <your_influxdb_port>
INFLUX_DB       = "<your_database>"
INFLUX_USER     = "<your_username>"
INFLUX_PASSWORD = "<your_password>"
CSV_PATH        = "env_data.csv"  # Generic path for public repo
BATCH_SIZE      = 5000

# ── SETUP LOGGING ─────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def nul_free_lines(path: str) -> Iterator[str]:
    """Yield lines from the CSV with any NUL characters removed."""
    with open(path, newline="") as f:
        for line in f:
            yield line.replace("\x00", "")

def read_csv_points(path: str, batch_size: int) -> Iterator[List[Dict]]:
    """
    Parse the CSV and yield lists of InfluxDB points in batches.
    """
    reader = csv.DictReader(nul_free_lines(path))
    batch: List[Dict] = []
    for row in reader:
        try:
            point = {
                "measurement": "environment",
                "tags": {"sensor": "dht22"},
                "time": row["timestamp"],
                "fields": {
                    "temperature_C": float(row["temperature_C"]),
                    "humidity": float(row["humidity_%"])
                }
            }
            batch.append(point)
        except (ValueError, KeyError) as e:
            logging.warning("Skipping invalid row %s: %s", row, e)
            continue

        if len(batch) >= batch_size:
            yield batch
            batch.clear()

    if batch:
        yield batch

def import_csv():
    """Import all CSV points into InfluxDB in batches."""
    client = InfluxDBClient(
        host=INFLUX_HOST,
        port=INFLUX_PORT,
        username=INFLUX_USER,
        password=INFLUX_PASSWORD,
        database=INFLUX_DB,
        timeout=30,
        retries=3
    )

    total = 0
    try:
        for batch in read_csv_points(CSV_PATH, BATCH_SIZE):
            try:
                client.write_points(batch, batch_size=BATCH_SIZE, time_precision='s')
                total += len(batch)
                logging.info("Imported batch of %d points (total: %d)", len(batch), total)
            except exceptions.InfluxDBClientError as e:
                logging.error("Failed to write batch: %s", e)
    finally:
        client.close()
        logging.info("Finished import: %d points imported into '%s'.", total, INFLUX_DB)

if __name__ == "__main__":
    import_csv() 