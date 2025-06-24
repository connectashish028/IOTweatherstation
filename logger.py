#!/usr/bin/env python3
import time
import csv
import logging
from datetime import datetime
import os
from logging.handlers import RotatingFileHandler
import traceback

import board
from adafruit_dht import DHT22
from influxdb import InfluxDBClient

# ── CONFIG ─────────────────────────────────────────────
DHT_PIN       = board.D4
USE_PULSEIO   = False
INTERVAL_SEC  = 5.0
CSV_PATH      = "env_data.csv"  # Generic path for public repo

# ── InfluxDB settings ─────────────────────────────────
INFLUX_HOST     = "<your_influxdb_host>"
INFLUX_PORT     = <your_influxdb_port>
INFLUX_DB       = "<your_database>"
INFLUX_USER     = "<your_username>"
INFLUX_PASSWORD = "<your_password>"

# ── SETUP LOGGING ─────────────────────────────────────
LOG_PATH = os.path.join(os.path.dirname(__file__), "dht_influx.log")
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S.%f")

# Console handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

# Rotating file handler
fh = RotatingFileHandler(LOG_PATH, maxBytes=2*1024*1024, backupCount=3)
fh.setFormatter(formatter)
logger.addHandler(fh)

def write_header_if_needed():
    try:
        with open(CSV_PATH, "x", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp","temperature_C","humidity_%"])
            logger.info("Created new CSV with header: %s", CSV_PATH)
    except FileExistsError:
        pass

def is_valid_reading(temp, hum):
    # DHT22: -40 to 80°C, 0-100% RH
    return (
        temp is not None and hum is not None and
        -40.0 <= temp <= 80.0 and 0.0 <= hum <= 100.0
    )

def retry(func, retries=3, delay=2, logger=None, context=""):
    for attempt in range(1, retries+1):
        try:
            return func()
        except Exception as e:
            if logger:
                logger.warning(f"Attempt {attempt} failed in {context}: {e}\n{traceback.format_exc()}")
            if attempt == retries:
                raise
            time.sleep(delay)

def main():
    # initialize sensor
    dht = DHT22(DHT_PIN, use_pulseio=USE_PULSEIO)

    # initialize InfluxDB client with retry
    def connect_influx():
        return InfluxDBClient(
            host=INFLUX_HOST,
            port=INFLUX_PORT,
            username=INFLUX_USER,
            password=INFLUX_PASSWORD,
            database=INFLUX_DB
        )
    influx = retry(connect_influx, retries=5, delay=5, logger=logger, context="InfluxDB connect")
    if influx is None:
        logger.error("Failed to connect to InfluxDB. Exiting.")
        return

    write_header_if_needed()

    try:
        with open(CSV_PATH, "a", newline="", buffering=1) as f:
            writer = csv.writer(f)

            while True:
                try:
                    # read sensor with retry
                    def read_sensor():
                        temp = dht.temperature
                        hum = dht.humidity
                        if not is_valid_reading(temp, hum):
                            raise RuntimeError(f"Invalid sensor reading: temp={temp}, hum={hum}")
                        return temp, hum
                    temp, hum = retry(read_sensor, retries=3, delay=2, logger=logger, context="DHT22 read")

                    # microsecond-precision UTC timestamp
                    now = datetime.utcnow().isoformat(timespec="microseconds")

                    # write CSV with error handling
                    try:
                        writer.writerow([now, f"{temp:.4f}", f"{hum:.4f}"])
                        logger.info(f"Logged CSV: {now}, {temp:.4f}°C, {hum:.4f}%")
                    except Exception as e:
                        logger.error(f"CSV write error: {e}\n{traceback.format_exc()}")

                    # write Influx with retry
                    def write_influx():
                        if temp is None or hum is None:
                            raise RuntimeError("Cannot write None values to InfluxDB.")
                        point = [{
                            "measurement": "environment",
                            "tags": {"sensor": "dht22"},
                            "time": now,
                            "fields": {
                                "temperature_C": float(temp),
                                "humidity": float(hum)
                            }
                        }]
                        influx.write_points(point)
                    try:
                        retry(write_influx, retries=3, delay=2, logger=logger, context="InfluxDB write")
                        logger.info(f"Wrote Influx: {temp:.4f}°C, {hum:.4f}%")
                    except Exception as e:
                        logger.error(f"Influx write error: {e}\n{traceback.format_exc()}")

                except Exception as e:
                    logger.warning(f"Read/Log error, skipping: {e}\n{traceback.format_exc()}")

                time.sleep(INTERVAL_SEC)

    except KeyboardInterrupt:
        logger.info("Interrupted by user, shutting down…")

    finally:
        dht.exit()
        if influx is not None:
            influx.close()
        logger.info("Cleanup complete, exiting.")

if __name__ == "__main__":
    main() 