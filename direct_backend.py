import os
import time


class DirectHID:
    """
    Direct backend for WH1080 using /dev/hidraw0.

    Avoids hidapi and libusb.
    """

    def __init__(self, device="/dev/hidraw0"):
        self.device = device

        print(f"DirectHID: opening {device}")

        self.fd = os.open(
            device,
            os.O_RDWR | os.O_NONBLOCK
        )

        print(f"DirectHID: fd={self.fd}")

    def __del__(self):
        try:
            if hasattr(self, "fd"):
                os.close(self.fd)
        except Exception:
            pass

    def write_data(self, buf):
        """
        Sends an 8-byte HID report.
        """

        data = bytes(buf)

        print(
            "DirectHID WRITE:",
            " ".join(f"{x:02x}" for x in data)
        )

        try:
            result = os.write(self.fd, data)

            print(
                "DirectHID WRITE RESULT:",
                result
            )

            if result != len(data):
                return False

            return True

        except Exception as e:
            print(
                "DirectHID WRITE ERROR:",
                repr(e)
            )
            return False

    def read_data(self, size):
        """
        pywws requests 32 bytes.

        WH1080 delivers this as 4 HID reports of 8 bytes each.
        """

        result = bytearray()

        deadline = time.monotonic() + 2.0

        while len(result) < size:

            if time.monotonic() > deadline:
                raise IOError(
                    "DirectHID: timeout waiting for data"
                )

            try:
                data = os.read(self.fd, 8)

                if not data:
                    continue

                print(
                    "DirectHID READ:",
                    len(data),
                    " ".join(f"{x:02x}" for x in data)
                )

                result.extend(data)

            except BlockingIOError:
                time.sleep(0.01)

            except Exception as e:
                raise IOError(
                    f"DirectHID read error: {e}"
                )

        return list(result[:size])
