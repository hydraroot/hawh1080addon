from direct_backend import DirectHID


print("=" * 60)
print(" WH1080 DIRECT PYWWS BACKEND TEST")
print("=" * 60)

dev = DirectHID("/dev/hidraw0")

address = 0x0110

command = [
    0xA1,
    address // 256,
    address % 256,
    0x20,

    0xA1,
    address // 256,
    address % 256,
    0x20,
]

print()
print("COMMAND:")
print(" ".join(f"{x:02x}" for x in command))

ok = dev.write_data(command)

print()
print("WRITE OK:", ok)

if not ok:
    raise SystemExit(1)

data = dev.read_data(32)

print()
print("RESULT:")
print(data)

print()
print("HEX:")
print(" ".join(f"{x:02x}" for x in data))

print()
print("=" * 60)
print(" FIN")
print("=" * 60)
