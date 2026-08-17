FROM python:3.14-alpine

ARG BUILD_VERSION

LABEL io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}"

# gcc/musl-dev/linux-headers/python3-dev are kept to build pywws and its
# dependencies. hidapi/libusb are NOT needed: the add-on talks directly to
# /dev/hidraw0 via syscalls (see direct_backend.py), it doesn't use those libs.
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    linux-headers \
    python3-dev

COPY requirements.txt /requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /requirements.txt

COPY direct_backend.py /direct_backend.py
COPY pywws_direct.py /pywws_direct.py
COPY wh1080.py /wh1080.py
COPY run.sh /run.sh

RUN chmod +x /run.sh

CMD ["/run.sh"]
