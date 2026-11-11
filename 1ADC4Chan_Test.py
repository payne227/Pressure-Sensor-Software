"""Save as main.py on the Pico; stream signed ADC counts to HeatMapInterp.py.

AIN0/AIN1 form the top row; AIN2/AIN3 form the bottom row.
Each input is measured against AINCOM. Timing assumes a 7.68 MHz ADC clock.
The PC scales positive counts to 0..65536 and keeps signed counts visible.
"""

from machine import Pin, SPI
import time
import json

# ------------------------------------------------------------
# SPI SETUP
# ------------------------------------------------------------
spi = SPI(
    0,
    baudrate=1_000_000,
    polarity=0,  # ADS1256 SPI mode 1: idle low, sample on falling edge
    phase=1,
    bits=8,
    firstbit=SPI.MSB,
    sck=Pin(18),
    mosi=Pin(19),
    miso=Pin(16)
)

# ------------------------------------------------------------
# SINGLE ADC CHIP SELECT
# ------------------------------------------------------------
CS = Pin(17, Pin.OUT, value=1)

# ------------------------------------------------------------
# SINGLE ADC DRDY PIN
# ------------------------------------------------------------
DRDY = Pin(20, Pin.IN)

# ------------------------------------------------------------
# ADS1256 COMMANDS
# ------------------------------------------------------------
CMD_WREG = 0x50
CMD_RREG = 0x10
CMD_SYNC = 0xFC
CMD_WAKEUP = 0x00
CMD_RDATA = 0x01
CMD_SDATAC = 0x0F
CMD_RESET = 0xFE
CMD_SELFCAL = 0xF0

# ------------------------------------------------------------
# LOW-LEVEL SPI HELPERS
# ------------------------------------------------------------
def cs_low():
    CS.value(0)

def cs_high():
    time.sleep_us(2)  # t10: hold CS low after the final clock edge
    CS.value(1)

def wait_drdy(timeout_ms=2000):
    started = time.ticks_ms()
    while DRDY.value() == 1:
        if time.ticks_diff(time.ticks_ms(), started) >= timeout_ms:
            raise OSError("ADS1256 DRDY timeout: check ADC power, GP20, RESET and SYNC/PDWN")
        time.sleep_us(10)

def write_cmd(cmd):
    cs_low()
    spi.write(bytearray([cmd]))
    cs_high()
    time.sleep_us(10)  # Includes SYNC-to-WAKEUP t11 delay

def write_reg(reg, value):
    cs_low()
    spi.write(bytearray([CMD_WREG | reg, 0x00, value]))
    cs_high()
    time.sleep_us(10)


def read_reg(reg):
    cs_low()
    spi.write(bytearray([CMD_RREG | reg, 0x00]))
    time.sleep_us(10)  # t6 before clocking register data
    value = spi.read(1)[0]
    cs_high()
    return value

def read_data():
    cs_low()

    spi.write(bytearray([CMD_RDATA]))
    time.sleep_us(10)

    raw = spi.read(3)

    cs_high()

    val = (raw[0] << 16) | (raw[1] << 8) | raw[2]

    if val & 0x800000:
        val -= 0x1000000

    return val

# ------------------------------------------------------------
# CONFIGURE ADS1256
# ------------------------------------------------------------
def init_ads1256():
    time.sleep_ms(100)
    write_cmd(CMD_RESET)
    time.sleep_ms(10)
    wait_drdy()
    write_cmd(CMD_SDATAC)  # Use explicit RDATA reads, not continuous-read mode
    write_reg(0x00, 0x00)  # STATUS: MSB first, auto-calibration off, buffer off
    write_reg(0x01, 0x08)  # MUX: AIN0/AINCOM
    write_reg(0x02, 0x00)  # ADCON: gain=1 (0x03 would select gain=8)
    write_reg(0x03, 0xA1)  # DRATE: 1000 SPS at 7.68 MHz
    write_cmd(CMD_SELFCAL)
    time.sleep_ms(1)
    wait_drdy()
    # Fail visibly if SPI writes/reads are not reaching the ADC correctly.
    for reg, expected, mask in ((0, 0x00, 0x0E), (1, 0x08, 0xFF),
                                (2, 0x00, 0x1F), (3, 0xA1, 0xFF)):
        actual = read_reg(reg)
        if actual & mask != expected:
            raise OSError(
                "ADS1256 register 0x{:02X}: got 0x{:02X}, expected 0x{:02X} (mask 0x{:02X}); check SPI wiring".format(
                    reg, actual, expected, mask
                )
            )

init_ads1256()

# ------------------------------------------------------------
# SET INPUT CHANNEL
# ------------------------------------------------------------
def set_channel(ch):
    mux = (ch << 4) | 0x08  # AINx vs AINCOM

    write_reg(0x01, mux)

    write_cmd(CMD_SYNC)
    write_cmd(CMD_WAKEUP)

# ------------------------------------------------------------
# READ 4 CHANNELS (AIN0-AIN3)
# ------------------------------------------------------------
def read_channels():
    results = []

    for ch in range(4):

        set_channel(ch)

        wait_drdy()

        val = read_data()

        results.append(val)

    return results

# ------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------
while True:

    results = read_channels()

    # One complete scan per USB line, ordered AIN0, AIN1, AIN2, AIN3.
    print("Results:", json.dumps(results))

    time.sleep(0.5)
