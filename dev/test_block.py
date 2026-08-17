import os
import time

DEVICE = "/dev/hidraw0"

print("==========================================")
print(" WH1080 DIRECT BLOCK READ TEST")
print("==========================================")

fd = os.open(DEVICE, os.O_RDWR)

print("OPEN OK")

def dump(label, data):
    print(label, "LEN:", len(data))
    print(label, "HEX:", " ".join(f"{x:02X}" for x in data))
    print(label, "LIST:", list(data))

# Primero hacemos exactamente la prueba que ya sabemos que funciona.
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

print()
print("COMMAND:", cmd.hex(" "))

n = os.write(fd, cmd)
print("WRITE:", n)

time.sleep(0.2)

data = os.read(fd, 32)
dump("RESPONSE", data)

os.close(fd)

print()
print("==========================================")
print(" FIN")
print("==========================================")
