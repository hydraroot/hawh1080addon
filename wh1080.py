#!/usr/bin/env python3

import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone, timedelta

import requests
import paho.mqtt.client as mqtt
import pywws.weatherstation as ws
from pywws_direct import DirectCUSBDrive

ws.CUSBDrive = DirectCUSBDrive

WeatherStation = ws.WeatherStation

# ============================================================
# CONFIG
# ============================================================

OPTIONS_FILE = "/data/options.json"

with open(OPTIONS_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

DEVICE = CONFIG.get("device", "/dev/hidraw0")

MQTT_CONFIG = CONFIG.get("mqtt", {})
MQTT_ENABLED = MQTT_CONFIG.get("enabled", True)
MQTT_HOST = MQTT_CONFIG.get("host", "core-mosquitto")
MQTT_PORT = int(MQTT_CONFIG.get("port", 1883))
MQTT_USERNAME = MQTT_CONFIG.get("username") or None
MQTT_PASSWORD = MQTT_CONFIG.get("password") or None

WU_CONFIG = CONFIG.get("weather_underground", {})
WU_ENABLED = WU_CONFIG.get("enabled", False)
WU_STATION_ID = WU_CONFIG.get("station_id", "")
WU_STATION_KEY = WU_CONFIG.get("station_key", "")
WU_INTERVAL = int(WU_CONFIG.get("interval", 60))

LOGGING_CONFIG = CONFIG.get("logging", {})

# Minimum number of seconds between MQTT publications.
#
# station.live_data() (pywws) already synchronizes readings with the
# console's internal clock - just like Cumulus MX does with its
# "Synchronise Reads and Writes" option - so new readings arrive on
# their own every ~43-48s, timed by the hardware.
#
# This value is just a safety floor to avoid spamming MQTT if two
# readings ever arrive close together (e.g. on reconnect after an
# outage). By default we leave it at 1s to publish as soon as the
# station communicates, just like Cumulus. If you want to force a
# longer publish interval, set it in "logging.interval" in the
# add-on options.
MIN_PUBLISH_INTERVAL = int(LOGGING_CONFIG.get("interval", 1))

UNITS_CONFIG = CONFIG.get("units", {})
UNIT_SYSTEM = UNITS_CONFIG.get("system", "metric")  # "metric" | "imperial"

if UNIT_SYSTEM not in ("metric", "imperial"):
    UNIT_SYSTEM = "metric"

IS_IMPERIAL = UNIT_SYSTEM == "imperial"

TEMP_SYMBOL = "°F" if IS_IMPERIAL else "°C"
PRESSURE_SYMBOL = "inHg" if IS_IMPERIAL else "hPa"
WIND_SPEED_SYMBOL = "mph" if IS_IMPERIAL else "km/h"
RAIN_SYMBOL = "in" if IS_IMPERIAL else "mm"
RAIN_RATE_SYMBOL = "in/h" if IS_IMPERIAL else "mm/h"

# ============================================================
# PHYSICALLY PLAUSIBLE RANGES
# ============================================================
#
# Filters out corrupted readings (typical of the direct /dev/hidraw0
# read hack, which sometimes returns frames with garbage bytes) so
# they don't create absurd daily max/min values.
#
# These are generous ranges (world records), not "typical for
# Buenos Aires": the idea is to discard only what is physically
# impossible, not to clip real extreme events (frosts, heatwaves, etc.).

TEMP_OUT_RANGE = (-40.0, 55.0)     # °C. World record: -89.2 / 56.7
TEMP_IN_RANGE = (-10.0, 55.0)      # °C. Console's indoor sensor
HUM_RANGE = (0.0, 100.0)           # %
PRESSURE_RANGE = (870.0, 1085.0)   # hPa. World pressure records
WIND_SPEED_RANGE = (0.0, 250.0)    # km/h. Above a category-5 hurricane
WIND_DIR_RANGE = (0.0, 360.0)      # degrees

# mm/h. The world's sustained record is around 300mm/h; above that
# it's almost certainly a corrupted rain counter reading, not a real
# storm. This threshold does NOT limit accumulated rain
# (rain / rain_today), it only discards the corrupt one-off "spike".
RAIN_RATE_SANITY_MAX_MMH = 500.0

# Argentina / Buenos Aires
LOCAL_TZ = timezone(timedelta(hours=-3))

DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "wh1080_usb"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

LOGGER = logging.getLogger("wh1080")

latest_data = None
latest_lock = threading.Lock()
mqtt_client = None


# ============================================================
# DAILY STATISTICS
# ============================================================

daily_stats = {
    "date": None,

    "max_wind_kmh": None,
    "max_wind_time": None,

    "max_gust_kmh": None,
    "max_gust_time": None,

    "min_temp_out": None,
    "min_temp_out_time": None,

    "max_temp_out": None,
    "max_temp_out_time": None,

    "min_hum_out": None,
    "min_hum_out_time": None,

    "max_hum_out": None,
    "max_hum_out_time": None,

    # Rain: the WH1080 provides an accumulated counter that never
    # resets on its own, so we keep our own daily baseline.
    "rain_baseline": None,
    "rain_today": None,
}

stats_lock = threading.Lock()

# Para calcular rain_rate (mm/h) necesitamos la lectura anterior.
_last_rain_value = None
_last_rain_time = None


# ============================================================
# MQTT
# ============================================================

def mqtt_connect():
    global mqtt_client

    if not MQTT_ENABLED:
        LOGGER.info("MQTT disabled")
        return

    LOGGER.info("Connecting MQTT: %s:%s", MQTT_HOST, MQTT_PORT)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="wh1080_usb",
    )

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            LOGGER.info("MQTT connected")
        else:
            LOGGER.error("MQTT connection failed: %s", reason_code)

    def on_disconnect(client, userdata, flags, reason_code, properties):
        LOGGER.warning("MQTT disconnected: %s", reason_code)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    while True:
        try:
            client.connect(
                MQTT_HOST,
                MQTT_PORT,
                keepalive=60,
            )
            client.loop_start()
            mqtt_client = client
            return

        except Exception as exc:
            LOGGER.error("MQTT connection error: %s", exc)
            time.sleep(10)


def mqtt_publish(topic, payload, retain=True):
    if not MQTT_ENABLED or mqtt_client is None:
        return

    try:
        mqtt_client.publish(
            topic,
            payload,
            qos=1,
            retain=retain,
        )

    except Exception as exc:
        LOGGER.error("MQTT publish error: %s", exc)


# ============================================================
# UTILITIES
# ============================================================

def safe_float(value):
    try:
        if value is None:
            return None

        value = float(value)

        if math.isnan(value) or math.isinf(value):
            return None

        return round(value, 2)

    except Exception:
        return None


def bounded(value, min_value, max_value, label):
    """
    Discards a value if it falls outside a physically possible range
    (typical of corrupted readings from the direct HID backend).
    Returns None and logs a warning in that case.
    """

    if value is None:
        return None

    if value < min_value or value > max_value:
        LOGGER.warning(
            "Reading discarded as out of range (%s): %s "
            "(expected between %s and %s)",
            label,
            value,
            min_value,
            max_value,
        )
        return None

    return value


def ms_to_kmh(value):
    if value is None:
        return None

    return round(float(value) * 3.6, 2)


def kmh_to_mph(value):
    if value is None:
        return None

    return round(float(value) * 0.621371192237, 2)


def mm_to_in(value):
    if value is None:
        return None

    return round(float(value) * 0.0393700787, 2)


def wind_speed_display(kmh_value):
    """Converts km/h -> mph if units.system=imperial in the config."""

    if kmh_value is None:
        return None

    if IS_IMPERIAL:
        return kmh_to_mph(kmh_value)

    return kmh_value


def temp_display(c_value):
    """Converts °C -> °F if units.system=imperial in the config."""

    if c_value is None:
        return None

    if IS_IMPERIAL:
        return c_to_f(c_value)

    return c_value


def pressure_display(hpa_value):
    """Converts hPa -> inHg if units.system=imperial in the config."""

    if hpa_value is None:
        return None

    if IS_IMPERIAL:
        return hpa_to_inhg(hpa_value)

    return hpa_value


def rain_display(mm_value):
    """Converts mm (or mm/h) -> in (or in/h) if units.system=imperial."""

    if mm_value is None:
        return None

    if IS_IMPERIAL:
        return mm_to_in(mm_value)

    return mm_value


def c_to_f(value):
    if value is None:
        return None

    return round(float(value) * 9.0 / 5.0 + 32.0, 2)


def hpa_to_inhg(value):
    if value is None:
        return None

    return round(float(value) * 0.0295299830714, 3)


def dew_point_c(temp_c, humidity):
    if temp_c is None:
        return None

    if humidity is None:
        return None

    if humidity <= 0:
        return None

    try:
        a = 17.625
        b = 243.04

        gamma = (
            math.log(humidity / 100.0)
            + (a * temp_c) / (b + temp_c)
        )

        return round(
            (b * gamma) / (a - gamma),
            2,
        )

    except Exception:
        return None


def wind_chill_c(temp_c, wind_kmh):
    """
    Wind chill.
    Formula used when:
      T <= 10°C
      wind > 4.8 km/h
    """

    if temp_c is None or wind_kmh is None:
        return None

    if temp_c > 10.0:
        return None

    if wind_kmh <= 4.8:
        return None

    try:
        wc = (
            13.12
            + 0.6215 * temp_c
            - 11.37 * (wind_kmh ** 0.16)
            + 0.3965 * temp_c * (wind_kmh ** 0.16)
        )

        return round(wc, 2)

    except Exception:
        return None


def wind_direction_text(degrees):
    if degrees is None:
        return None

    try:
        directions = [
            "N",
            "NNE",
            "NE",
            "ENE",
            "E",
            "ESE",
            "SE",
            "SSE",
            "S",
            "SSW",
            "SW",
            "WSW",
            "W",
            "WNW",
            "NW",
            "NNW",
        ]

        index = int((float(degrees) + 11.25) / 22.5) % 16

        return directions[index]

    except Exception:
        return None


# ============================================================
# STATISTICS
# ============================================================

def reset_daily_stats(date_value):
    global daily_stats

    daily_stats = {
        "date": date_value,

        "max_wind_kmh": None,
        "max_wind_time": None,

        "max_gust_kmh": None,
        "max_gust_time": None,

        "min_temp_out": None,
        "min_temp_out_time": None,

        "max_temp_out": None,
        "max_temp_out_time": None,

        "min_hum_out": None,
        "min_hum_out_time": None,

        "max_hum_out": None,
        "max_hum_out_time": None,

        "rain_baseline": None,
        "rain_today": None,
    }


def validate_rain(rain_total):
    """
    Validates the accumulated rain counter reading and calculates
    the intensity (mm/h) by comparing it against the previous
    reading.

    If the implied rate exceeds RAIN_RATE_SANITY_MAX_MMH (well above
    any real storm, see the comment on its definition), THAT specific
    reading is discarded as corrupt: rain/rain_rate/rain_today are not
    updated this cycle, but real rain isn't "lost" either — the next
    good reading is compared against the last reliable value, not
    against the corrupt one.

    Returns (valid_rain, rain_rate).
    """

    global _last_rain_value, _last_rain_time

    if rain_total is None:
        return None, None

    if rain_total < 0:
        LOGGER.warning(
            "Rain reading discarded (negative): %s",
            rain_total,
        )
        return None, None

    now = time.monotonic()

    rate = None

    if _last_rain_value is not None and _last_rain_time is not None:

        dt_hours = (now - _last_rain_time) / 3600.0

        if dt_hours > 0:

            delta = rain_total - _last_rain_value

            if delta < 0:
                # Counter reset (station reboot / overflow): treat it
                # as a new baseline, no rate calculated this cycle.
                pass

            else:
                candidate_rate = delta / dt_hours

                if candidate_rate > RAIN_RATE_SANITY_MAX_MMH:

                    LOGGER.warning(
                        "Rain reading discarded as implausible: "
                        "%.1f mm/h (> %.0f mm/h). rain=%s previous=%s",
                        candidate_rate,
                        RAIN_RATE_SANITY_MAX_MMH,
                        rain_total,
                        _last_rain_value,
                    )

                    # We don't trust this one-off reading: we don't
                    # update the last known value and don't publish
                    # any rain data this cycle.
                    return None, None

                rate = round(candidate_rate, 2)

    _last_rain_value = rain_total
    _last_rain_time = now

    return rain_total, rate


def update_daily_stats(data):
    now_local = datetime.now(LOCAL_TZ)
    today = now_local.strftime("%d/%m/%Y")

    with stats_lock:

        if daily_stats["date"] != today:
            reset_daily_stats(today)

        # Human-readable format with year, including the sensed value
        # (built below, value by value, with its unit).
        timestamp = now_local.strftime("%d/%m/%Y %H:%M:%S")

        wind = data.get("wind_kmh")
        gust = data.get("wind_gust_kmh")
        temp = data.get("temp_out")
        hum = data.get("hum_out")
        rain_total = data.get("rain")

        # ----------------------------------------------------
        # RAIN ACCUMULATED TODAY
        # ----------------------------------------------------

        if rain_total is not None:

            if daily_stats["rain_baseline"] is None:
                daily_stats["rain_baseline"] = rain_total

            today_rain = rain_total - daily_stats["rain_baseline"]

            # If it comes out negative, the station reset its
            # internal counter; we take the current value as the
            # new baseline to avoid reporting negative rain.
            if today_rain < 0:
                daily_stats["rain_baseline"] = rain_total
                today_rain = 0.0

            daily_stats["rain_today"] = round(today_rain, 2)

        # ----------------------------------------------------
        # MAX WIND
        # ----------------------------------------------------

        if wind is not None:

            if (
                daily_stats["max_wind_kmh"] is None
                or wind > daily_stats["max_wind_kmh"]
            ):
                daily_stats["max_wind_kmh"] = wind
                daily_stats["max_wind_time"] = (
                    f"{wind} {WIND_SPEED_SYMBOL} — {timestamp}"
                )

        # ----------------------------------------------------
        # MAX GUST
        # ----------------------------------------------------

        if gust is not None:

            if (
                daily_stats["max_gust_kmh"] is None
                or gust > daily_stats["max_gust_kmh"]
            ):
                daily_stats["max_gust_kmh"] = gust
                daily_stats["max_gust_time"] = (
                    f"{gust} {WIND_SPEED_SYMBOL} — {timestamp}"
                )

        # ----------------------------------------------------
        # MIN/MAX TEMPERATURE
        # ----------------------------------------------------

        if temp is not None:

            if (
                daily_stats["min_temp_out"] is None
                or temp < daily_stats["min_temp_out"]
            ):
                daily_stats["min_temp_out"] = temp
                daily_stats["min_temp_out_time"] = (
                    f"{temp} {TEMP_SYMBOL} — {timestamp}"
                )

            if (
                daily_stats["max_temp_out"] is None
                or temp > daily_stats["max_temp_out"]
            ):
                daily_stats["max_temp_out"] = temp
                daily_stats["max_temp_out_time"] = (
                    f"{temp} {TEMP_SYMBOL} — {timestamp}"
                )

        # ----------------------------------------------------
        # MIN/MAX HUMIDITY
        # ----------------------------------------------------

        if hum is not None:

            if (
                daily_stats["min_hum_out"] is None
                or hum < daily_stats["min_hum_out"]
            ):
                daily_stats["min_hum_out"] = hum
                daily_stats["min_hum_out_time"] = (
                    f"{hum} % — {timestamp}"
                )

            if (
                daily_stats["max_hum_out"] is None
                or hum > daily_stats["max_hum_out"]
            ):
                daily_stats["max_hum_out"] = hum
                daily_stats["max_hum_out_time"] = (
                    f"{hum} % — {timestamp}"
                )

        data.update({
            "max_wind_kmh": daily_stats["max_wind_kmh"],
            "max_wind_time": daily_stats["max_wind_time"],

            "max_gust_kmh": daily_stats["max_gust_kmh"],
            "max_gust_time": daily_stats["max_gust_time"],

            "min_temp_out": daily_stats["min_temp_out"],
            "min_temp_out_time": daily_stats["min_temp_out_time"],

            "max_temp_out": daily_stats["max_temp_out"],
            "max_temp_out_time": daily_stats["max_temp_out_time"],

            "min_hum_out": daily_stats["min_hum_out"],
            "min_hum_out_time": daily_stats["min_hum_out_time"],

            "max_hum_out": daily_stats["max_hum_out"],
            "max_hum_out_time": daily_stats["max_hum_out_time"],

            "rain_today": daily_stats["rain_today"],

            "stats_date": daily_stats["date"],
        })


# ============================================================
# NORMALIZATION
# ============================================================

def normalize(data):

    temp_out = bounded(
        safe_float(data.get("temp_out")),
        *TEMP_OUT_RANGE,
        "temp_out",
    )
    temp_in = bounded(
        safe_float(data.get("temp_in")),
        *TEMP_IN_RANGE,
        "temp_in",
    )

    hum_out = bounded(
        safe_float(data.get("hum_out")),
        *HUM_RANGE,
        "hum_out",
    )
    hum_in = bounded(
        safe_float(data.get("hum_in")),
        *HUM_RANGE,
        "hum_in",
    )

    pressure = bounded(
        safe_float(data.get("abs_pressure")),
        *PRESSURE_RANGE,
        "abs_pressure",
    )

    wind_ms = safe_float(data.get("wind_ave"))
    gust_ms = safe_float(data.get("wind_gust"))

    wind_kmh = bounded(
        ms_to_kmh(wind_ms),
        *WIND_SPEED_RANGE,
        "wind_kmh",
    )
    gust_kmh = bounded(
        ms_to_kmh(gust_ms),
        *WIND_SPEED_RANGE,
        "wind_gust_kmh",
    )

    # ------------------------------------------------------------
    # WIND DIRECTION CONVERSION (INDEX 0-15 -> DEGREES)
    # ------------------------------------------------------------
    # The WH1080 delivers an integer from 0 to 15 representing the
    # vane's position (16 cardinal directions).
    # Each step is 22.5° (360/16).
    # Example: 8 -> 8 * 22.5 = 180° (South)
    wind_dir_raw = bounded(
        safe_float(data.get("wind_dir")),
        0,
        15,
        "wind_dir",
    )
    if wind_dir_raw is not None:
        # Round to integer in case it arrives as a float (e.g. 8.0)
        wind_dir = round(int(round(wind_dir_raw)) * 22.5, 1)
    else:
        wind_dir = None

    rain_raw = safe_float(data.get("rain"))
    rain, rain_rate = validate_rain(rain_raw)

    dew = dew_point_c(
        temp_out,
        hum_out,
    )

    chill = wind_chill_c(
        temp_out,
        wind_kmh,
    )

    # From here on we convert everything to the unit chosen in the
    # config (units.system: metric | imperial). The calculations
    # above (dew point, wind_chill) were already done in metric,
    # which is what those formulas require, so they aren't affected.
    result = {
        # ----------------------------------------------------
        # GENERAL
        # ----------------------------------------------------

        "delay": data.get("delay", 0),

        # ----------------------------------------------------
        # TEMPERATURE
        # ----------------------------------------------------

        "temp_in": temp_display(temp_in),
        "temp_out": temp_display(temp_out),

        # ----------------------------------------------------
        # HUMIDITY (always %, no conversion)
        # ----------------------------------------------------

        "hum_in": hum_in,
        "hum_out": hum_out,

        # ----------------------------------------------------
        # PRESSURE
        # ----------------------------------------------------

        "abs_pressure": pressure_display(pressure),

        # ----------------------------------------------------
        # WIND
        # ----------------------------------------------------

        # Original from pywws
        "wind_ms": wind_ms,
        "wind_gust_ms": gust_ms,

        # What we'll use in Home Assistant (configurable unit,
        # see units.system in the add-on config)
        "wind_kmh": wind_speed_display(wind_kmh),
        "wind_gust_kmh": wind_speed_display(gust_kmh),

        "wind_dir": wind_dir,
        "wind_dir_text": wind_direction_text(wind_dir),

        # ----------------------------------------------------
        # RAIN
        # ----------------------------------------------------

        "rain": rain_display(rain),
        "rain_rate": rain_display(rain_rate),

        # ----------------------------------------------------
        # CALCULATED
        # ----------------------------------------------------

        "dew_point": temp_display(dew),
        "wind_chill": temp_display(chill),

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        "lost_connection": bool(
            data.get("status", {}).get(
                "lost_connection",
                False,
            )
        ),

        "rain_overflow": bool(
            data.get("status", {}).get(
                "rain_overflow",
                False,
            )
        ),

        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),

        # ----------------------------------------------------
        # RAW METRIC VALUES (internal use only, e.g. Weather
        # Underground, which always needs imperial regardless of
        # which unit you chose for Home Assistant)
        # ----------------------------------------------------

        "_raw_temp_out_c": temp_out,
        "_raw_abs_pressure_hpa": pressure,
        "_raw_wind_kmh": wind_kmh,
        "_raw_gust_kmh": gust_kmh,
        "_raw_dew_point_c": dew,
    }

    update_daily_stats(result)

    return result


# ============================================================
# MQTT DISCOVERY
# ============================================================

def publish_discovery():

    if not MQTT_ENABLED:
        return

    device = {
        "identifiers": [DEVICE_ID],
        "name": "WH1080",
        "manufacturer": "Fine Offset",
        "model": "WH1080",
    }

    sensors = [

        # ----------------------------------------------------
        # TEMPERATURE
        # ----------------------------------------------------

        (
            "temperature_outside",
            "Temperature Outside",
            "temp_out",
            TEMP_SYMBOL,
            "temperature",
            "measurement",
        ),

        (
            "temperature_inside",
            "Temperature Inside",
            "temp_in",
            TEMP_SYMBOL,
            "temperature",
            "measurement",
        ),

        # ----------------------------------------------------
        # HUMEDAD
        # ----------------------------------------------------

        (
            "humidity_outside",
            "Humidity Outside",
            "hum_out",
            "%",
            "humidity",
            "measurement",
        ),

        (
            "humidity_inside",
            "Humidity Inside",
            "hum_in",
            "%",
            "humidity",
            "measurement",
        ),

        # ----------------------------------------------------
        # PRESSURE
        # ----------------------------------------------------

        (
            "pressure",
            "Absolute Pressure",
            "abs_pressure",
            PRESSURE_SYMBOL,
            "pressure",
            "measurement",
        ),

        # ----------------------------------------------------
        # WIND
        # ----------------------------------------------------

        (
            "wind_speed",
            "Wind Speed",
            "wind_kmh",
            WIND_SPEED_SYMBOL,
            "wind_speed",
            "measurement",
        ),

        (
            "wind_gust",
            "Wind Gust",
            "wind_gust_kmh",
            WIND_SPEED_SYMBOL,
            "wind_speed",
            "measurement",
        ),

        (
            "wind_direction",
            "Wind Direction",
            "wind_dir",
            "°",
            None,
            "measurement",
        ),

        (
            "wind_direction_text",
            "Wind Direction Cardinal",
            "wind_dir_text",
            None,
            None,
            None,
        ),

        # ----------------------------------------------------
        # RAIN
        # ----------------------------------------------------

        (
            "rain",
            "Rain Total",
            "rain",
            RAIN_SYMBOL,
            None,
            "total_increasing",
        ),

        (
            "rain_rate",
            "Rain Rate",
            "rain_rate",
            RAIN_RATE_SYMBOL,
            "precipitation_intensity",
            "measurement",
        ),

        (
            "rain_today",
            "Rain Today",
            "rain_today",
            RAIN_SYMBOL,
            None,
            "total_increasing",
        ),

        # ----------------------------------------------------
        # CALCULATED
        # ----------------------------------------------------

        (
            "dew_point",
            "Dew Point",
            "dew_point",
            TEMP_SYMBOL,
            "temperature",
            "measurement",
        ),

        (
            "wind_chill",
            "Wind Chill",
            "wind_chill",
            TEMP_SYMBOL,
            "temperature",
            "measurement",
        ),

        # ----------------------------------------------------
        # TODAY'S MAXIMUMS
        # ----------------------------------------------------

        (
            "max_wind",
            "Maximum Wind Today",
            "max_wind_kmh",
            WIND_SPEED_SYMBOL,
            "wind_speed",
            "measurement",
        ),

        (
            "max_gust",
            "Maximum Gust Today",
            "max_gust_kmh",
            WIND_SPEED_SYMBOL,
            "wind_speed",
            "measurement",
        ),

        # ----------------------------------------------------
        # TODAY'S TEMPERATURE
        # ----------------------------------------------------

        (
            "min_temperature_today",
            "Minimum Temperature Today",
            "min_temp_out",
            TEMP_SYMBOL,
            "temperature",
            "measurement",
        ),

        (
            "max_temperature_today",
            "Maximum Temperature Today",
            "max_temp_out",
            TEMP_SYMBOL,
            "temperature",
            "measurement",
        ),

        # ----------------------------------------------------
        # TODAY'S HUMIDITY
        # ----------------------------------------------------

        (
            "min_humidity_today",
            "Minimum Humidity Today",
            "min_hum_out",
            "%",
            "humidity",
            "measurement",
        ),

        (
            "max_humidity_today",
            "Maximum Humidity Today",
            "max_hum_out",
            "%",
            "humidity",
            "measurement",
        ),
    ]

    for item in sensors:

        key, name, state, unit, device_class, state_class = item

        payload = {
            "name": name,
            "unique_id": f"{DEVICE_ID}_{key}",
            "state_topic": "wh1080/state",
            "value_template": (
                f"{{{{ value_json.{state} }}}}"
            ),
            "device": device,
            "availability_topic": "wh1080/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

        if state_class:
            payload["state_class"] = state_class

        if unit:
            payload["unit_of_measurement"] = unit

        if device_class:
            payload["device_class"] = device_class

        topic = (
            f"{DISCOVERY_PREFIX}/sensor/"
            f"{DEVICE_ID}/{key}/config"
        )

        mqtt_publish(
            topic,
            json.dumps(payload),
        )

    # --------------------------------------------------------
    # TEXT SENSORS
    # --------------------------------------------------------

    text_sensors = [

        (
            "max_gust_time",
            "Maximum Gust Time",
            "max_gust_time",
        ),

        (
            "max_wind_time",
            "Maximum Wind Time",
            "max_wind_time",
        ),

        (
            "min_temp_time",
            "Minimum Temperature Time",
            "min_temp_out_time",
        ),

        (
            "max_temp_time",
            "Maximum Temperature Time",
            "max_temp_out_time",
        ),

        (
            "min_hum_time",
            "Minimum Humidity Time",
            "min_hum_out_time",
        ),

        (
            "max_hum_time",
            "Maximum Humidity Time",
            "max_hum_out_time",
        ),

        (
            "stats_date",
            "Statistics Date",
            "stats_date",
        ),
    ]

    for key, name, state in text_sensors:

        payload = {
            "name": name,
            "unique_id": f"{DEVICE_ID}_{key}",
            "state_topic": "wh1080/state",
            "value_template": (
                f"{{{{ value_json.{state} }}}}"
            ),
            "device": device,
            "availability_topic": "wh1080/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

        topic = (
            f"{DISCOVERY_PREFIX}/sensor/"
            f"{DEVICE_ID}/{key}/config"
        )

        mqtt_publish(
            topic,
            json.dumps(payload),
        )

    # --------------------------------------------------------
    # CONNECTION
    # --------------------------------------------------------

    binary_payload = {
        "name": "WH1080 Connection",
        "unique_id": f"{DEVICE_ID}_connection",
        "state_topic": "wh1080/availability",
        "payload_on": "online",
        "payload_off": "offline",
        "device_class": "connectivity",
        "device": device,
    }

    mqtt_publish(
        f"{DISCOVERY_PREFIX}/binary_sensor/"
        f"{DEVICE_ID}/connection/config",
        json.dumps(binary_payload),
    )

    LOGGER.info("MQTT Discovery published")


# ============================================================
# MQTT STATE
# ============================================================

def publish_data(data):

    mqtt_publish(
        "wh1080/state",
        json.dumps(
            data,
            separators=(",", ":"),
        ),
    )

    mqtt_publish(
        "wh1080/availability",
        "offline"
        if data["lost_connection"]
        else "online",
    )

    LOGGER.info("========== ALL WH1080 DATA ==========")
    for key, value in data.items():
        LOGGER.info("%s = %s", key, value)
    LOGGER.info("============================================")

    LOGGER.info(
        "WH1080: "
        "T_out=%s" + TEMP_SYMBOL + " "
        "H_out=%s%% "
        "P=%s" + PRESSURE_SYMBOL + " "
        "Wind=%s" + WIND_SPEED_SYMBOL + " "
        "Gust=%s" + WIND_SPEED_SYMBOL + " "
        "Dir=%s°(%s) "
        "Rain=%s" + RAIN_SYMBOL + " "
        "Dew=%s" + TEMP_SYMBOL + " "
        "Chill=%s" + TEMP_SYMBOL + " "
        "MaxGust=%s" + WIND_SPEED_SYMBOL,

        data["temp_out"],
        data["hum_out"],
        data["abs_pressure"],
        data["wind_kmh"],
        data["wind_gust_kmh"],
        data["wind_dir"],
        data["wind_dir_text"],
        data["rain"],
        data["dew_point"],
        data["wind_chill"],
        data["max_gust_kmh"],
    )


# ============================================================
# WEATHER UNDERGROUND
# ============================================================

WU_URLS = [
    "https://rtupdate.wunderground.com/weatherstation/updateweatherstation.php",
    "https://weatherstation.wunderground.com/weatherstation/updateweatherstation.php",
]


def upload_weather_underground(data):

    if not WU_ENABLED:
        return

    if not WU_STATION_ID or not WU_STATION_KEY:

        LOGGER.warning(
            "Weather Underground enabled "
            "but credentials are empty"
        )

        return

    params = {
        "ID": WU_STATION_ID,
        "PASSWORD": WU_STATION_KEY,

        "dateutc": "now",
        "action": "updateraw",

        "softwaretype": "HAOS-WH1080-2.0",

        "tempf": c_to_f(
            data.get("_raw_temp_out_c")
        ),

        "humidity": data.get(
            "hum_out"
        ),

        "baromin": hpa_to_inhg(
            data.get("_raw_abs_pressure_hpa")
        ),

        "windspeedmph": kmh_to_mph(
            data.get("_raw_wind_kmh")
        ),

        "windgustmph": kmh_to_mph(
            data.get("_raw_gust_kmh")
        ),

        "winddir": data.get(
            "wind_dir"
        ),

        "dewptf": c_to_f(
            data.get("_raw_dew_point_c")
        ),
    }

    params = {
        k: v
        for k, v in params.items()
        if v is not None
    }

    for url in WU_URLS:

        try:

            LOGGER.info(
                "Weather Underground upload..."
            )

            response = requests.get(
                url,
                params=params,
                timeout=15,
            )

            text = response.text.strip()

            LOGGER.info(
                "Weather Underground response: %s",
                text[:200],
            )

            if (
                response.ok
                and "success" in text.lower()
            ):

                LOGGER.info(
                    "Weather Underground upload OK"
                )

                return

        except Exception as exc:

            LOGGER.warning(
                "Weather Underground error: %s",
                exc,
            )

    LOGGER.error(
        "Weather Underground upload failed"
    )


def weather_underground_loop():

    if not WU_ENABLED:
        return

    LOGGER.info(
        "Weather Underground uploader "
        "enabled (every %s seconds)",
        WU_INTERVAL,
    )

    while True:

        try:

            with latest_lock:

                data = (
                    dict(latest_data)
                    if latest_data is not None
                    else None
                )

            if data is not None:
                upload_weather_underground(
                    data
                )

        except Exception:

            LOGGER.exception(
                "Weather Underground loop error"
            )

        time.sleep(
            WU_INTERVAL
        )


# ============================================================
# STATION
# ============================================================

def weather_station_loop():

    global latest_data

    # Start at 0 minus the interval, so the first reading that
    # arrives is always published immediately (doesn't wait 43s).
    last_publish_at = -MIN_PUBLISH_INTERVAL
    last_reading_at = None

    while True:

        try:

            LOGGER.info(
                "Connecting to WH1080..."
            )

            station = WeatherStation()

            LOGGER.info(
                "WH1080 connected"
            )

            LOGGER.info(
                "Station type: %s",
                station.ws_type,
            )

            LOGGER.info(
                "Current position: %s",
                station.current_pos(),
            )

            generator = station.live_data()

            for item in generator:

                try:

                    now = time.monotonic()

                    # Informational log: how often new sensor readings
                    # arrive (should be around ~43-48s, set by the
                    # WH1080's hardware).
                    if last_reading_at is not None:
                        LOGGER.info(
                            "WH1080: new reading %.1fs "
                            "after the previous one",
                            now - last_reading_at,
                        )
                    last_reading_at = now

                    raw_data = item[0]

                    data = normalize(
                        raw_data
                    )

                    with latest_lock:
                        latest_data = data

                    # Throttle: don't publish to MQTT more often than
                    # MIN_PUBLISH_INTERVAL, in case readings arrive
                    # closer together than normal (e.g. on reconnect).
                    if (now - last_publish_at) >= MIN_PUBLISH_INTERVAL:
                        publish_data(data)
                        last_publish_at = now
                    else:
                        LOGGER.debug(
                            "WH1080: reading received but not "
                            "published (throttled to %ss)",
                            MIN_PUBLISH_INTERVAL,
                        )

                except Exception:

                    LOGGER.exception(
                        "Error processing WH1080 data"
                    )

        except KeyboardInterrupt:

            raise

        except Exception:

            LOGGER.exception(
                "WH1080 connection/read error"
            )

            try:

                mqtt_publish(
                    "wh1080/availability",
                    "offline",
                )

            except Exception:

                pass

            LOGGER.info(
                "Retrying WH1080 in 10 seconds..."
            )

            time.sleep(10)


# ============================================================
# MAIN
# ============================================================

def main():

    LOGGER.info(
        "=========================================="
    )

    LOGGER.info(
        "WH1080 USB Weather Station starting"
    )

    LOGGER.info(
        "Device: %s",
        DEVICE,
    )

    LOGGER.info(
        "=========================================="
    )

    if not os.path.exists(DEVICE):

        LOGGER.error(
            "Device does not exist: %s",
            DEVICE,
        )

        raise SystemExit(1)

    if MQTT_ENABLED:

        mqtt_connect()

        time.sleep(2)

        publish_discovery()

        mqtt_publish(
            "wh1080/availability",
            "offline",
        )

    if WU_ENABLED:

        threading.Thread(
            target=weather_underground_loop,
            daemon=True,
        ).start()

    weather_station_loop()


if __name__ == "__main__":
    main()

