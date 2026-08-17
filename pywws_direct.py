import pywws.weatherstation as ws

from direct_backend import DirectHID


class DirectCUSBDrive:
    """
    Replacement for pywws' CUSBDrive.

    Uses /dev/hidraw0 directly.
    """

    EndMark = 0x20
    ReadCommand = 0xA1
    WriteCommand = 0xA0
    WriteCommandWord = 0xA2

    def __init__(self):
        print("DirectCUSBDrive: initializing")

        self.dev = DirectHID("/dev/hidraw0")

        print("DirectCUSBDrive: OK")

    def read_block(self, address):

        print(
            f"DirectCUSBDrive: read_block "
            f"address=0x{address:04x}"
        )

        buf = [
            self.ReadCommand,
            address // 256,
            address % 256,
            self.EndMark,

            self.ReadCommand,
            address // 256,
            address % 256,
            self.EndMark,
        ]

        print(
            "DirectCUSBDrive COMMAND:",
            " ".join(f"{x:02x}" for x in buf)
        )

        if not self.dev.write_data(buf):
            print("DirectCUSBDrive: WRITE FAILED")
            return None

        data = self.dev.read_data(32)

        print(
            "DirectCUSBDrive: READ:",
            " ".join(f"{x:02x}" for x in data)
        )

        return data

    def write_byte(self, address, data):

        buf = [
            self.WriteCommandWord,
            address // 256,
            address % 256,
            self.EndMark,

            self.WriteCommandWord,
            data,
            0,
            self.EndMark,
        ]

        if not self.dev.write_data(buf):
            return False

        response = self.dev.read_data(8)

        if response is None:
            return False

        return all(x == 0xA5 for x in response)


# Replace pywws' original backend
ws.CUSBDrive = DirectCUSBDrive

print("PYWWS: CUSBDrive replaced with DirectCUSBDrive")
