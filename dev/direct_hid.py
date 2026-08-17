import os
import time
import select


class DirectHID:

    def __init__(self, device="/dev/hidraw0"):
        self.device = device

        self.fd = os.open(
            self.device,
            os.O_RDWR | os.O_NONBLOCK
        )

        print(f"DirectHID: opened {self.device}")
        print(f"DirectHID: fd={self.fd}")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def write_data(self, data):
        if self.fd is None:
            return False

        # pywws passes a list of integers.
        packet = bytes(data)

        print(
            "DirectHID WRITE:",
            packet.hex(" ")
        )

        try:
            n = os.write(self.fd, packet)

            print(
                "DirectHID WRITE RESULT:",
                n
            )

            return n == len(packet)

        except Exception as e:
            print(
                "DirectHID WRITE ERROR:",
                repr(e)
            )
            return False

    def read_data(self, length):

        if self.fd is None:
            return None

        result = bytearray()

        deadline = time.monotonic() + 2.0

        while len(result) < length:

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                break

            try:
                ready, _, _ = select.select(
                    [self.fd],
                    [],
                    [],
                    min(remaining, 0.2)
                )

                if not ready:
                    continue

                chunk = os.read(
                    self.fd,
                    64
                )

                if chunk:
                    print(
                        "DirectHID READ:",
                        len(chunk),
                        chunk.hex(" ")
                    )

                    result.extend(chunk)

            except BlockingIOError:
                time.sleep(0.01)

            except Exception as e:
                print(
                    "DirectHID READ ERROR:",
                    repr(e)
                )
                return None

        if len(result) < length:
            print(
                f"DirectHID: expected {length}, "
                f"got {len(result)}"
            )

            return None

        return list(result[:length])
