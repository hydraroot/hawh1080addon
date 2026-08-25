# WH1080 USB Weather Station for Home Assistant

Home Assistant App for reading a **Fine Offset WH1080** weather station and compatible models directly through USB.

The App reads the weather station through `/dev/hidraw0`, uses **pywws** to communicate with and decode WH1080-family weather station data, publishes the readings to Home Assistant through **MQTT Discovery**, and can optionally send data to **Weather Underground**.

## Overview

This project was developed to provide a simple way to connect a WH1080 weather station directly to a machine running **Home Assistant OS** through USB.

The intended setup is:

**WH1080 console → USB → Home Assistant OS → MQTT Discovery**

No SDR receiver or additional Raspberry Pi is required for this setup.

## Features

- Direct USB HID access through `/dev/hidraw0`
- Fine Offset WH1080 support
- Compatible WH1080-family stations
- MQTT Discovery
- Automatic Home Assistant entities
- Automatic reconnection
- Metric and Imperial units
- Outdoor and indoor measurements
- Wind measurements
- Rain measurements
- Daily maximum/minimum values
- Data validation against physically impossible readings
- Connection/availability status
- Optional Weather Underground integration

## Supported hardware

The project has been tested with:

- **Fine Offset WH1080**

The following models are intended to be compatible, but additional testing is welcome:

- WH1081
- WH1090
- WH1091
- Other Fine Offset or rebranded stations using the same USB protocol

If you test another compatible model, please report the exact model and whether it works correctly.

## Sensors

The App publishes the following information to Home Assistant:

- Outdoor temperature
- Outdoor humidity
- Indoor temperature
- Indoor humidity
- Atmospheric pressure
- Wind speed
- Wind gust
- Maximum wind gust
- Wind direction in degrees
- Wind direction as compass text
- Dew point
- Wind chill
- Total accumulated rainfall
- Rainfall accumulated today
- Estimated rain intensity
- Daily maximum and minimum values
- Timestamps for daily maximum/minimum values
- Connection/availability status

## Rain measurements

The WH1080 provides an accumulated rainfall counter.

This project uses the following values:

- `rain`: the accumulated rainfall counter supplied by the station.
- `rain_today`: calculated from the first valid reading of the day.
- `rain_rate`: estimated by comparing consecutive rainfall readings.

The accumulated rainfall counter is not artificially limited.

A corrupted one-off reading can produce an unrealistic rain-rate value. Such an isolated `rain_rate` spike is discarded when it exceeds approximately **500 mm/h**.

## Units

The App supports Metric and Imperial units.

Example configuration:

```yaml
units:
  system: metric
```

or:

```yaml
units:
  system: imperial
```

### Metric

- Temperature: °C
- Pressure: hPa
- Wind: km/h
- Rain: mm

### Imperial

- Temperature: °F
- Pressure: inHg
- Wind: mph
- Rain: in

The selected unit system affects the Home Assistant sensors, including:

- Temperature
- Pressure
- Wind
- Rain
- Dew point
- Wind chill
- Daily maximum/minimum values

After changing the unit system, save the App configuration and allow the App to restart.

### Changing units during the day

Daily maximum/minimum values are stored using the selected unit system.

If the unit system is changed during the day, comparisons with previously stored values from that same day may temporarily appear inconsistent until the next daily reset.

This does not affect real-time readings or the accumulated rainfall counter.

Weather Underground uploads use the units required by its API independently of the Home Assistant unit selection.

## Update frequency

The App does not use a fixed timer such as "publish every 10 seconds".

A new reading is published when the WH1080 console receives a new reading from the outdoor sensor.

The interval is controlled by the weather station hardware. In normal operation, the console typically receives a new outdoor reading approximately every **43–48 seconds**.

The App uses the `pywws` live-data mechanism to synchronize reads with the console's internal timing and avoid interfering with a write operation.

There is also a configurable safety interval in the logging configuration to prevent readings from being processed more frequently than expected.

Example log message:

```text
WH1080: new reading 47.2s after the previous one
```

This can be used to verify the actual update interval of the connected station.

## Corrupt reading protection

The direct `/dev/hidraw0` backend can occasionally receive an invalid or corrupted USB frame.

To prevent an invalid frame from affecting stored daily maximum/minimum values, readings are checked against physically plausible limits before being accepted.

| Field | Accepted range |
|---|---:|
| Outdoor temperature | -40 °C to 55 °C |
| Indoor temperature | -10 °C to 55 °C |
| Humidity | 0 % to 100 % |
| Atmospheric pressure | 870 hPa to 1085 hPa |
| Wind speed / gust | 0 to 250 km/h |
| Wind direction | 0° to 360° |

These limits are intended to reject physically impossible values while still allowing extreme real-world weather events.

If a reading falls outside the accepted range, that reading is discarded for that cycle and a warning is written to the log.

Subsequent readings continue to be processed normally.

Accumulated rainfall is handled separately because legitimate extreme rainfall can produce high accumulated values. The accumulated `rain` and `rain_today` values are therefore not clamped.

## Wind direction

The WH1080 family does not provide wind direction directly as a 0–360° value.

The station provides a **16-position index from 0 to 15**:

```text
0  = N
1  = NNE
2  = NE
3  = ENE
4  = E
5  = ESE
6  = SE
7  = SSE
8  = S
9  = SSW
10 = SW
11 = WSW
12 = W
13 = WNW
14 = NW
15 = NNW
```

The conversion to degrees is:

```text
degrees = wind_direction_index × 22.5
```

For example:

```text
8 → 180° → S
```

The WH1080 raw protocol uses the 16-position index. The App converts this representation into degrees and compass text for Home Assistant.

## Installation

This App is intended for **Home Assistant OS**.

Home Assistant currently refers to these components as **Apps** (formerly Add-ons).

### Add the repository

1. Open **Settings → Apps**.
2. Open the **App Store / Install app** section.
3. Open the **⋮** menu in the top-right corner.
4. Select **Repositories**.
5. Add this repository:

```text
https://github.com/hydraroot/hawh1080addon
```

6. Add the repository.
7. Refresh the App store if necessary.
8. Select **WH1080 USB Weather Station**.
9. Select **Install**.

### Home Assistant OS requirement

Home Assistant Apps are available when using the **Home Assistant OS** installation method.

Other Home Assistant installation methods do not provide the same Supervisor/App environment.

## USB device

The WH1080 console must be accessible to the App through:

```text
/dev/hidraw0
```

Connect the WH1080 console to the Home Assistant OS machine through USB.

If the App cannot communicate with the station, check the App logs and verify that the USB device is detected correctly.

## First start

For the first test, Weather Underground can be left disabled:

```yaml
weather_underground:
  enabled: false
```

Start the App and check its logs.

Once the WH1080 is communicating correctly and Home Assistant entities are being created through MQTT Discovery, Weather Underground can be enabled if required.

## MQTT

The App requires an MQTT broker reachable from Home Assistant OS.

A typical Home Assistant OS installation using the Mosquitto Broker App can use:

```yaml
host: core-mosquitto
port: 1883
```

If the MQTT broker uses different settings, configure the appropriate broker address and port in the App configuration.

## Weather Underground

Weather Underground support is optional and disabled by default.

Before enabling it:

1. Verify the Weather Underground credentials.
2. Verify the PWS configuration.
3. Enable Weather Underground in the App configuration.
4. Check the App logs for successful updates.

Weather Underground uploads use the units required by its API.

The WH1080 accumulated rainfall counter is not currently sent as an instantaneous `rainin` value because the station's rainfall counter represents accumulated rainfall rather than an instantaneous rate.

## Third-party software

This project uses **pywws**, an open-source Python software package for USB wireless weather stations.

`pywws` provides functionality for communicating with and decoding data from Fine Offset / WH1080-family weather stations. It is installed as a third-party dependency and is maintained separately from this Home Assistant App.

The dependency is specified in `requirements.txt`.

**pywws project:**

https://github.com/jim-easterbrook/pywws

**pywws license:** GNU General Public License version 2 or later (GPLv2+).

This project adds the Home Assistant integration layer around the weather-station functionality, including:

- Home Assistant App packaging
- USB device access through `/dev/hidraw0`
- Configuration handling
- MQTT Discovery
- Home Assistant entity publishing
- Availability handling
- Reading validation
- Unit conversion
- Daily maximum/minimum handling
- Optional Weather Underground integration

Third-party software remains subject to its respective license terms.

## Repository structure

This repository contains a single Home Assistant App.

```text
hawh1080addon/
├── repository.yaml
├── config.yaml
├── Dockerfile
├── run.sh
├── wh1080.py
├── pywws_direct.py
├── direct_backend.py
├── requirements.txt
├── dev/
│   ├── requirements-dev.txt
│   └── test_*.py
├── LICENSE
└── README.md
```

The files in the repository root are part of the WH1080 App.

The `dev/` directory contains development and diagnostic material used during development and testing. These files are not required for normal operation of the App.

## Development notes

The project includes a direct USB backend designed to communicate with the WH1080 console through `/dev/hidraw0`.

The development material includes diagnostic tools and experiments used to investigate the WH1080 USB/HID protocol.

## Configuration version

The Home Assistant App version is defined in:

```text
config.yaml
```

For a new release, update the `version` field in that file.

Example:

```yaml
version: "1.0.1"
```

## Dependencies

Runtime dependencies are listed in:

```text
requirements.txt
```

The project currently uses:

- `pywws`
- `paho-mqtt`
- `requests`

Third-party dependencies are installed separately and remain subject to their respective licenses.

## Limitations

- The project has currently been tested directly with a Fine Offset WH1080.
- Compatibility with other WH1080-family models should be confirmed with real hardware.
- The WH1080 console must be accessible through `/dev/hidraw0`.
- Weather Underground support is optional.
- `rain_today` and `rain_rate` are calculated values rather than raw fields directly supplied by the station.
- Additional hardware testing is welcome.

## Feedback and testing

Testing with additional WH1080-family stations and different Home Assistant OS hardware is welcome.

When reporting a problem, please include:

- Exact weather station model
- Home Assistant OS hardware
- Home Assistant OS version
- Whether the USB console is detected
- Relevant App log messages
- Whether MQTT entities were created successfully

## Acknowledgements

Thanks to the developers and contributors of **pywws** for their work supporting Fine Offset and compatible weather stations.

## License

The original code developed for this project is released under the **MIT License**.

Third-party software and dependencies remain subject to their respective licenses.

See the `LICENSE` file for the MIT License applying to the original project code.
