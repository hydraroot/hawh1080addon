import sys
import usb.core
import usb.util

VID = 0x1941
PID = 0x8021

print("=" * 60)
print(" WH1080 PYUSB TEST")
print("=" * 60)

print("PyUSB:", usb.__version__)

print("Buscando dispositivo...")
dev = usb.core.find(idVendor=VID, idProduct=PID)

if dev is None:
    print("ERROR: dispositivo no encontrado")
    sys.exit(1)

print("OK: dispositivo encontrado")
print("VID:", hex(dev.idVendor))
print("PID:", hex(dev.idProduct))

print("Configuration...")
try:
    dev.set_configuration()
    print("OK set_configuration")
except Exception as e:
    print("set_configuration:", repr(e))

print("Reclamando interface 0...")

try:
    if dev.is_kernel_driver_active(0):
        print("Kernel driver activo -> intentando detach")
        dev.detach_kernel_driver(0)
except Exception as e:
    print("detach:", repr(e))

try:
    usb.util.claim_interface(dev, 0)
    print("OK claim_interface")
except Exception as e:
    print("ERROR claim:", repr(e))
    sys.exit(1)

# WH1080 / pywws protocol
address = 0x0110

command = [
    0xA1,
    address // 256,
    address % 256,
    0x20,
    0xA1,
    address // 256,
    address % 256,
    0x20
]

print()
print("COMMAND:")
print(" ".join(f"{x:02x}" for x in command))

try:
    # pywws uses control transfer:
    # OUT | CLASS | INTERFACE
    # SET_CONFIGURATION
    # wValue = 0x200
    result = dev.ctrl_transfer(
        bmRequestType=(
            usb.util.CTRL_OUT |
            usb.util.CTRL_TYPE_CLASS |
            usb.util.CTRL_RECIPIENT_INTERFACE
        ),
        bRequest=usb.CTRL_SET_CONFIGURATION,
        wValue=0x200,
        wIndex=0,
        data_or_wLength=command,
        timeout=1000
    )

    print("CONTROL WRITE RESULT:", result)

except Exception as e:
    print("CONTROL WRITE ERROR:", repr(e))
    usb.util.release_interface(dev, 0)
    sys.exit(1)

print()
print("Leyendo endpoint 0x81...")

data = []

try:
    for i in range(4):
        r = dev.read(0x81, 8, timeout=1500)
        r = list(r)

        print(
            f"READ {i}:",
            len(r),
            " ".join(f"{x:02x}" for x in r)
        )

        data.extend(r)

except Exception as e:
    print("READ ERROR:", repr(e))

print()
print("TOTAL:", len(data))
print("TOTAL HEX:")
print(" ".join(f"{x:02x}" for x in data))

try:
    usb.util.release_interface(dev, 0)
except Exception:
    pass

print()
print("=" * 60)
print(" FIN")
print("=" * 60)
