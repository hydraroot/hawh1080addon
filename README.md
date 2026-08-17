# WH1080 USB Weather Station for Home Assistant

**Author:** Walter Diego Spaltro ([@hydraroot](https://github.com/hydraroot))
**Repository:** [github.com/hydraroot/hawh1080addon](https://github.com/hydraroot/hawh1080addon)

Home Assistant add-on to read a Fine Offset WH1080 weather station
(and compatibles: WH1081, WH1090, WH1091, and several rebrands of the
same chipset) directly over USB, without going through hidapi/libusb,
using `pywws` over `/dev/hidraw0`. Publishes data via MQTT Discovery
(automatic sensors in Home Assistant) and optionally to Weather
Underground.

Reads a Fine Offset WH1080 directly over USB from Home Assistant OS.

## Features

- USB HID `/dev/hidraw0`
- pywws 25.10.0
- MQTT Discovery
- Automatic sensors in Home Assistant
- Automatic reconnection
- Optional Weather Underground

## Published sensors

Temperature (indoor/outdoor), humidity (indoor/outdoor), pressure,
wind (speed, gust, direction in degrees and text), dew point, wind
chill, total rain (station's accumulated counter), **rain intensity**
and **rain accumulated today**, plus the day's max/min values with
their timestamp (including min/max humidity time).

> `rain` is the accumulated counter that never resets on its own
> (that's how the WH1080 delivers it). `rain_today` is calculated
> using the first reading of each day as a baseline, and `rain_rate`
> is estimated by comparing each reading against the previous one.

## Units (Metric / Imperial)

In the add-on's configuration tab (next to MQTT and Weather
Underground) there's a `units.system` selector:

```yaml
units:
  system: metric   # or "imperial"
```

- `metric`: °C, hPa, km/h, mm
- `imperial`: °F, inHg, mph, in

It affects **all** the sensors shown in Home Assistant (temperature,
pressure, wind, rain, dew point, wind chill, and the day's
max/min values). Changing it requires **restarting the add-on** for
it to take effect (Home Assistant restarts the container when you
save the configuration, so saving and waiting for the restart is
enough).

Uploads to **Weather Underground are always sent in imperial units**,
regardless of what you choose here, because that's what its API
requires — nothing needs to be changed for that.

> Note: the day's max/min values (`max_wind`, `min_temp_out`, etc.)
> are already stored in the chosen unit. If you switch systems
> **mid-day**, the comparison of those min/max values may look odd
> until the next midnight (they reset every day at 00:00 local time).
> It does not affect `rain`, `rain_today`, or real-time data.

## Update frequency

There's no internal timer publishing "every N seconds": data is
published to MQTT every time the WH1080 delivers a new reading from
the outdoor sensor, and that's timed by the station's hardware (it
syncs by RF with the sensor every ~43-48s — it's not something the
add-on controls).

`station.live_data()` (from `pywws`) synchronizes readings with the
console's internal clock, just like Cumulus MX's **"Synchronise Reads
and Writes"** option: it schedules each read right after the console
updates its data, avoiding clashing with a write in progress.

There's a configurable safety floor in `logging.interval` (seconds,
default `1`) to avoid publishing more often than that — useful only
if two readings ever arrive closer together than normal (for example
right after reconnecting following an outage). With the default of
`1`, in practice data is published to MQTT as soon as the station
communicates, just like Cumulus MX does.

In the logs you'll see a message like:
```
WH1080: new reading 47.2s after the previous one
```
which confirms live how often your console is syncing.

## Corrupt reading filter

The backend reads `/dev/hidraw0` directly (without the robust
validation that pywws includes with the "normal" USB protocol), so
every once in a while it can return a frame with garbage bytes. To
keep that from ruining the day's max/min values, every reading is
validated against a physically possible range before being stored:

| Field | Accepted range |
|---|---|
| Outdoor temperature | -40°C to 55°C |
| Indoor temperature | -10°C to 55°C |
| Humidity | 0% to 100% |
| Pressure | 870 hPa to 1085 hPa |
| Wind / gust | 0 to 250 km/h |
| Wind direction | 0° to 360° |

These are world-record ranges, not "typical for Buenos Aires": the
idea is to discard only what's physically impossible (backend
glitches), not to clip a real, strong event. If a reading falls
outside the range, that specific reading is discarded (it stays as
`None` for that cycle) and a warning is logged; it doesn't affect
subsequent readings.

**Rain**: here you have to be more careful, because a strong storm or
a real flood *can* legitimately produce high values. That's why
accumulated rain (`rain`, `rain_today`) is never clamped at all —
only a one-off `rain_rate` spike is discarded if it implies an
intensity above ~500 mm/h, well above the sustained world record
(~300 mm/h), a value that can only come from a corrupt counter
reading, not real rain.

## Technical note: wind direction (`wind_dir`)

The WH1080 (and its whole family: WH1081, WH1090, WH1091, rebrands)
doesn't deliver wind direction in degrees directly: it delivers an
**index from 0 to 15** representing one of the 16 points of the
compass rose.

```
0  = N     4  = E     8  = S     12 = W
1  = NNE   5  = ESE   9  = SSW   13 = WNW
2  = NE    6  = SE    10 = SW    14 = NW
3  = ENE   7  = SSE   11 = WSW   15 = NNW
```

To convert that index to degrees:

```python
degrees = wind_dir_index * 22.5
```

`pywws` already knows this format when decoding the data block; the
important thing is not to treat that value as if it were already
degrees in some intermediate layer (a common mistake when writing
your own parsing/normalization).

## Repo structure

The GitHub repo root looks like this (this matters for Option A above
— it's what the Supervisor expects from an add-on repository). In
this repo, `config.yaml` lives directly at the repo root, so it's a
**single-add-on repository**:

```
hawh1080addon/            # repo root = this repo
├── repository.yaml       # repo metadata (name, url, maintainer)
├── wh1080.py              # main loop + MQTT + discovery
├── pywws_direct.py        # replaces pywws' USB backend
├── direct_backend.py      # direct access to /dev/hidraw0
├── Dockerfile
├── run.sh
├── config.yaml
├── requirements.txt
└── dev/                   # diagnostic scripts, NOT copied into the image
    ├── requirements-dev.txt
    └── test_*.py
```

The scripts in `dev/` were used to reverse-engineer the WH1080's HID
protocol (raw block reads, pyusb/hidapi tests, etc.). They're kept as
reference but aren't part of the production add-on.

## Installation

### Option A — Add-on Store via GitHub (recommended)

Once this repo is on GitHub, Home Assistant can install it directly
from there, without manually copying files onto the box:

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ (top
   right) → Repositories**.
2. Add this URL:
   ```
   https://github.com/hydraroot/hawh1080addon
   ```
3. Close the dialog and refresh the Add-on Store. A new entry
   **"WH1080 USB Weather Station"** will show up under the added
   repository.
4. Click it, then **Install**.

This works because the repo root has a `repository.yaml` (repo
metadata) right next to `config.yaml` and the rest of the add-on
files — that's the layout the Supervisor expects for a single-add-on
GitHub repository (no extra subfolder needed).

To publish an update later, bump `version` in `wh1080_usb/config.yaml`
(e.g. `"1.0.1"`) and push the commit; Home Assistant will offer the
update in the Add-on Store like any other add-on.

### Option B — Manual copy

Copy this folder to `/addons/wh1080_usb/`.

The WH1080 must show up as `/dev/hidraw0`.

Keep Weather Underground disabled at first:

```yaml
weather_underground:
  enabled: false
```

Start the add-on and check the logs.

## MQTT

Requires Mosquitto Broker or an MQTT broker reachable from the
add-on.

By default:

```yaml
host: core-mosquitto
port: 1883
```

## Weather Underground

The integration is included but disabled by default.

Don't enable it until you've verified your credentials and the PWS
update endpoint.

Accumulated rain isn't sent yet as `rainin`, to avoid misinterpreting
the WH1080's rain counter.
