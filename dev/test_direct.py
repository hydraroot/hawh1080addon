import os
import time

DEVICE = "/dev/hidraw0"

print("==========================================")
print(" WH1080 DIRECT HIDRAW TEST")
print("==========================================")

print("DEVICE:", DEVICE)

print("exists:", os.path.exists(DEVICE))
print("access R:", os.access(DEVICE, os.R_OK))
print("access W:", os.access(DEVICE, os.W_OK))

fd = os.open(DEVICE, os.O_RDWR)

print("OPEN OK")
print("FD:", fd)

cmd = bytes([
    0xA1,
    0x00,
    0x00,
    0x20,
    0xA1,
    0x00,
    0x00,
    0x20
])

print("WRITE:", cmd.hex(" "))

n = os.write(fd, cmd)

print("WRITE BYTES:", n)

time.sleep(0.5)

try:
    data = os.read(fd, 32)

    print("READ LEN:", len(data))
    print("READ HEX:", data.hex(" "))
    print("READ LIST:", list(data))

except Exception as e:
    print("READ ERROR:", repr(e))

os.close(fd)

print("==========================================")
print(" FIN")
print("==========================================")
