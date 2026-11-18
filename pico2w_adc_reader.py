from machine import Pin, SPI
import time

# ------------------------------------------------------------
# SPI SETUP (shared by all ADS1256 modules)
# ------------------------------------------------------------
spi = SPI(
    0,
    baudrate=1_000_000,
    polarity=1,
    phase=1,
    bits=8,
    firstbit=SPI.MSB,
    sck=Pin(18),
    mosi=Pin(19),
    miso=Pin(16)
)

# ------------------------------------------------------------
# CHIP SELECT PINS
# ------------------------------------------------------------
CS_PINS = [
    Pin(17, Pin.OUT, value=1),  # ADC0
    Pin(14, Pin.OUT, value=1),  # ADC1
    Pin(13, Pin.OUT, value=1),  # ADC2
    Pin(12, Pin.OUT, value=1)   # ADC3
]

# ------------------------------------------------------------
# DRDY PINS
# ------------------------------------------------------------
DRDY_PINS = [
    Pin(20, Pin.IN),  # ADC0
    Pin(21, Pin.IN),  # ADC1
    Pin(22, Pin.IN),  # ADC2
    Pin(26, Pin.IN)   # ADC3
]

# ------------------------------------------------------------
# ADS1256 COMMANDS
# ------------------------------------------------------------
CMD_WREG   = 0x50
CMD_RREG   = 0x10
CMD_SYNC   = 0xFC
CMD_WAKEUP = 0x00
CMD_RDATA  = 0x01

# ------------------------------------------------------------
# SPI HELPERS
# ------------------------------------------------------------
def cs_low(i):
    CS_PINS[i].value(0)

def cs_high(i):
    CS_PINS[i].value(1)

def write_cmd(i, cmd):
    cs_low(i)
    spi.write(bytearray([cmd]))
    cs_high(i)

def write_reg(i, reg, value):
    cs_low(i)
    spi.write(bytearray([CMD_WREG | reg, 0x00, value]))
    cs_high(i)

def wait_drdy(i, timeout_ms=100):
    start = time.ticks_ms()

    while DRDY_PINS[i].value() == 1:
        if time.ticks_diff(time.ticks_ms(), start) >= timeout_ms:
            return False

    return True

def read_data(i):
    cs_low(i)

    spi.write(bytearray([CMD_RDATA]))
    time.sleep_us(10)

    raw = spi.read(3)

    cs_high(i)

    if raw is None or len(raw) != 3:
        raise RuntimeError("SPI read failed")

    value = (raw[0] << 16) | (raw[1] << 8) | raw[2]

    if value & 0x800000:
        value -= 0x1000000

    return value

# ------------------------------------------------------------
# ADS1256 INITIALIZATION
# ------------------------------------------------------------
def init_ads1256(i):
    try:
        write_reg(i, 0x00, 0x01)  # STATUS
        write_reg(i, 0x01, 0x00)  # MUX
        write_reg(i, 0x02, 0x03)  # ADCON gain=1
        write_reg(i, 0x03, 0xF0)  # 1000 SPS

        write_cmd(i, CMD_SYNC)
        write_cmd(i, CMD_WAKEUP)

        return wait_drdy(i)

    except Exception:
        return False

# ------------------------------------------------------------
# SET INPUT CHANNEL
# ------------------------------------------------------------
def set_channel(i, ch):
    mux = (ch << 4) | 0x08

    write_reg(i, 0x01, mux)

    write_cmd(i, CMD_SYNC)
    write_cmd(i, CMD_WAKEUP)

# ------------------------------------------------------------
# READ ALL 8 CHANNELS FROM ONE ADC
# ------------------------------------------------------------
def read_all_channels(i):

    readings = []

    for ch in range(8):

        try:
            set_channel(i, ch)

            if not wait_drdy(i):
                readings.append(0)
                continue

            value = read_data(i)
            readings.append(value)

        except Exception:
            readings.append(0)

    return readings

# ------------------------------------------------------------
# INITIALIZE ALL ADCS
# ------------------------------------------------------------
adc_active = []

print("Initializing ADS1256 modules...")

for adc in range(4):

    online = init_ads1256(adc)

    adc_active.append(online)

    if online:
        print("ADC{} ONLINE".format(adc))
    else:
        print("ADC{} OFFLINE".format(adc))

# ------------------------------------------------------------
# MAIN LOOP
#
# PC PROGRAM EXPECTS:
# Results: [8 integers]
#
# We are currently using ADC0 as the 8-channel source for
# the heatmap application.
# ------------------------------------------------------------
while True:

    try:

        if adc_active[0]:

            readings = read_all_channels(0)

            if len(readings) != 8:
                readings = [0] * 8

        else:
            readings = [0] * 8

        print("Results:", readings)

    except Exception:

        print("Results:", [0,0,0,0,0,0,0,0])

    time.sleep(0.05)
