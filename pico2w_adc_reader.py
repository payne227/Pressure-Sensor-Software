from machine import Pin, SPI
import time

# ------------------------------------------------------------
# SPI SETUP (shared by all 4 ADS1256 modules)
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
# CHIP SELECT PINS (one per ADC)
# ------------------------------------------------------------
CS_PINS = [
    Pin(17, Pin.OUT, value=1),  # ADC 0
    Pin(14, Pin.OUT, value=1),  # ADC 1
    Pin(13, Pin.OUT, value=1),  # ADC 2
    Pin(12, Pin.OUT, value=1)   # ADC 3
]

# ------------------------------------------------------------
# DRDY PINS (one per ADC)
# ------------------------------------------------------------
DRDY_PINS = [
    Pin(20, Pin.IN),  # ADC 0
    Pin(21, Pin.IN),  # ADC 1
    Pin(22, Pin.IN),  # ADC 2
    Pin(26, Pin.IN)   # ADC 3
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
# LOW-LEVEL SPI HELPERS
# ------------------------------------------------------------
def cs_low(i):
    CS_PINS[i].value(0)

def cs_high(i):
    CS_PINS[i].value(1)

def wait_drdy(i, timeout_ms=100):
    """
    Wait for DRDY to go low.
    Returns True if conversion ready.
    Returns False if timeout occurs.
    """
    start = time.ticks_ms()

    while DRDY_PINS[i].value() == 1:
        if time.ticks_diff(time.ticks_ms(), start) >= timeout_ms:
            return False

    return True

def write_cmd(i, cmd):
    cs_low(i)
    spi.write(bytearray([cmd]))
    cs_high(i)

def write_reg(i, reg, value):
    cs_low(i)
    spi.write(bytearray([CMD_WREG | reg, 0x00, value]))
    cs_high(i)

def read_data(i):
    cs_low(i)
    spi.write(bytearray([CMD_RDATA]))
    time.sleep_us(10)
    raw = spi.read(3)
    cs_high(i)

    val = (raw[0] << 16) | (raw[1] << 8) | raw[2]

    if val & 0x800000:
        val -= 0x1000000

    return val

# ------------------------------------------------------------
# CONFIGURE EACH ADS1256
# ------------------------------------------------------------
def init_ads1256(i):

    try:
        write_reg(i, 0x00, 0x01)  # STATUS: buffer off
        write_reg(i, 0x01, 0x00)  # MUX: AIN0/AINCOM
        write_reg(i, 0x02, 0x03)  # ADCON: gain=1
        write_reg(i, 0x03, 0xF0)  # DRATE: 1000 SPS

        write_cmd(i, CMD_SYNC)
        write_cmd(i, CMD_WAKEUP)

        if wait_drdy(i):
            return True
        else:
            return False

    except Exception as e:
        print("ADC", i, "init exception:", e)
        return False

# ------------------------------------------------------------
# SET INPUT CHANNEL
# ------------------------------------------------------------
def set_channel(i, ch):
    mux = (ch << 4) | 0x08  # AINx vs AINCOM

    write_reg(i, 0x01, mux)
    write_cmd(i, CMD_SYNC)
    write_cmd(i, CMD_WAKEUP)

# ------------------------------------------------------------
# READ ALL 8 CHANNELS FROM ONE ADC
# ------------------------------------------------------------
def read_all_channels(i):

    results = []

    for ch in range(8):

        set_channel(i, ch)

        if not wait_drdy(i):
            print("ADC", i, "timeout on channel", ch)
            results.append(None)
            continue

        val = read_data(i)
        results.append(val)

    return results

# ------------------------------------------------------------
# INITIALIZE ADCs
# ------------------------------------------------------------
adc_active = []

print("Initializing ADS1256 modules...")

for i in range(4):

    if init_ads1256(i):
        print("ADC", i, "ONLINE")
        adc_active.append(True)
    else:
        print("ADC", i, "OFFLINE")
        adc_active.append(False)

print()

# ------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------
while True:

    all_data = []

    for adc in range(4):

        if adc_activech_data = read_all_channels(adc)

            # If every channel timed out, mark ADC offline
            if all(v is None for v in ch_data):
                print("ADC", adc, "lost communication")
                adc_active[adc] = False
                ch_data = ["OFFLINE"] * 8
        else:
            ch_data = ["OFFLINE"] * 8

        all_data.append(ch_data)

    print("ADC0:", all_data[0])
    print("ADC1:", all_data[1])
    print("ADC2:", all_data[2])
    print("ADC3:", all_data[3])
    print("--------------------------------------------------")

    time.sleep(0.5)
