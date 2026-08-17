import os
import time
import hid

VID = 0x1941
PID = 0x8021

print("=" * 50)
print(" WH1080 HID REPORT TEST")
print("=" * 50)

print("Enumeration:")
for d in hid.enumerate(VID, PID):
    print(d)

dev = hid.device()
dev.open(VID, PID)

print("OPEN OK")

# pywws CUSBDrive.read_block(0)
cmd = bytes([
    0xA1, 0x00, 0x00, 0x20,
    0xA1, 0x00, 0x00, 0x20
])

tests = [
    ("SIN REPORT ID", cmd),
    ("CON REPORT ID 00", b"\x00" + cmd),
]

for name, packet in tests:
    print()
    print("=" * 50)
    print(name)
    print("WRITE:", packet.hex(" "))

    try:
        n = dev.write(packet)
        print("WRITE RESULT:", n)

        time.sleep(0.1)

        data = dev.read(33, timeout_ms=1000)

        print("READ LEN:", len(data))
        print("READ HEX:", bytes(data).hex(" "))
        print("READ LIST:", list(data))

    except Exception as e:
        print("ERROR:", repr(e))

dev.close()

print()
print("=" * 50)
print("FIN")
print("=" * 50)
