import os
import time

DEV = "/dev/hidraw0"

print("=" * 60)
print(" WH1080 DIRECT HIDRAW BLOCK TEST")
print("=" * 60)

fd = os.open(DEV, os.O_RDWR | os.O_NONBLOCK)

print("OPEN OK")
print("FD:", fd)

def test_address(address):
    print()
    print("-" * 60)
    print("ADDRESS:", hex(address), address)

    cmd = bytes([
        0xA1,
        (address >> 8) & 0xFF,
        address & 0xFF,
        0x20,
        0xA1,
        (address >> 8) & 0xFF,
        address & 0xFF,
        0x20
    ])

    print("COMMAND:", cmd.hex(" "))

    try:
        n = os.write(fd, cmd)
        print("WRITE:", n)
    except Exception as e:
        print("WRITE ERROR:", repr(e))
        return

    time.sleep(0.1)

    data = b""

    for i in range(20):
        try:
            chunk = os.read(fd, 64)

            if chunk:
                data += chunk
                print(
                    "READ",
                    i,
                    "LEN=", len(chunk),
                    "HEX=", chunk.hex(" ")
                )

                if len(data) >= 32:
                    break

        except BlockingIOError:
            time.sleep(0.05)

        except Exception as e:
            print("READ ERROR:", repr(e))
            break

    print("TOTAL:", len(data))
    print("TOTAL HEX:", data.hex(" "))

addresses = [
    0x0000,
    0x0020,
    0x0100,
    0x0110,
    0x0120,
    0x0200,
    0x1000,
]

for address in addresses:
    test_address(address)
    time.sleep(0.2)

os.close(fd)

print()
print("=" * 60)
print(" FIN")
print("=" * 60)
