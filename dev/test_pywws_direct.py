print("=" * 60)
print(" WH1080 PYWWS DIRECT DATA TEST")
print("=" * 60)

import traceback

import pywws_direct
from pywws.weatherstation import WeatherStation


print()
print("Creando WeatherStation()...")

try:

    station = WeatherStation()

    print()
    print("==========================================")
    print(" WEATHERSTATION OK")
    print("==========================================")

    print()
    print("Intentando get_current()...")

    try:

        data = station.get_current()

        print()
        print("==========================================")
        print(" DATOS ACTUALES")
        print("==========================================")

        print("TYPE:", type(data))
        print("DATA:", data)

        if data:
            try:
                print()
                print("KEYS:")
                print(list(data.keys()))
            except Exception:
                pass

    except Exception:

        print()
        print("ERROR EN get_current():")
        traceback.print_exc()


except Exception:

    print()
    print("ERROR CREANDO WEATHERSTATION:")
    traceback.print_exc()


print()
print("=" * 60)
print(" FIN")
print("=" * 60)

