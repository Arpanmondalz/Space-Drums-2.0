# Space Drums 2.0 — Pin Mapping

This document details the hardware pin connections and definitions for the **Space Drums 2.0** hardware. 

**Target Microcontroller:** ESP32-S3-MINI-1-N8

## Hardware Notes

* **GPIO0:** Boot strap pin for download mode.
* **UART0:** Used for standard serial communication/flashing (`TXD0` = GPIO43, `RXD0` = GPIO44).
* **USB:** Native USB support is routed through GPIO19 (D-) and GPIO20 (D+).
* **Power:** `3V3` is the main module supply; `GND` is common ground.

---

## Pinout Table

| ESP32 Pin | Net / Component(s) | Description / Function |
| :--- | :--- | :--- |
| **GPIO0** | `IO0` / SW2 / R5 | Boot button / Download mode |
| **GPIO4** | `VBAT_SENSE` / R9, R10, C21 | Battery voltage ADC sense (via voltage divider) |
| **GPIO5** | `IMU1_CS` / U5 (ICM-42688-P) | SPI Chip Select for IMU 1 |
| **GPIO6** | `IMU1_INT` / U5 | Hardware interrupt from IMU 1 |
| **GPIO7** | `SDA` / U8, U7 | I2C Data (shared by Magnetometer & Haptic Driver) |
| **GPIO8** | `SCL` / U8, U7 | I2C Clock (shared by Magnetometer & Haptic Driver) |
| **GPIO9** | `IMU2_CS` / U4 (ICM-42688-P) | SPI Chip Select for IMU 2 |
| **GPIO10** | `IMU2_INT` / U4 | Hardware interrupt from IMU 2 |
| **GPIO11** | `KILL` / U10 (LTC2954) | Power-hold / kill line to power controller |
| **GPIO12** | `INT` / U10 (LTC2954) | Power controller interrupt to ESP32 |
| **GPIO19** | `USB_D-` | Native USB D− (through series resistor) |
| **GPIO20** | `USB_D+` | Native USB D+ (through series resistor) |
| **GPIO35** | `SPI_MOSI` | SPI MOSI (to both IMUs) |
| **GPIO36** | `SPI_SCK` | SPI Clock (to both IMUs) |
| **GPIO37** | `SPI_MISO` | SPI MISO (from both IMUs) |
| **GPIO41** | `LED1` / R18 | Status LED |
| **GPIO43** | `UART0_TX` / H1 | Serial TX / U0TXD |
| **GPIO44** | `UART0_RX` / H1 | Serial RX / U0RXD |

---

## Arduino IDE Pin Definitions

```cpp
// Space Drums 2.0 — ESP32-S3-MINI-1-N8 Pin Map

// --- System & Power ---
#define PIN_BOOT_BTN        GPIO_NUM_0     // BOOT button to GND
#define PIN_VBAT_SENSE      GPIO_NUM_4     // Battery divider ADC
#define PIN_PMIC_KILL       GPIO_NUM_11    // LTC2954 KILL
#define PIN_PMIC_INT        GPIO_NUM_12    // LTC2954 INT
#define PIN_STATUS_LED      GPIO_NUM_41    // Status indicator

// --- SPI Bus (IMUs) ---
#define PIN_SPI_MOSI        GPIO_NUM_35
#define PIN_SPI_MISO        GPIO_NUM_37
#define PIN_SPI_SCK         GPIO_NUM_36
#define PIN_IMU1_CS         GPIO_NUM_5     // ICM-42688-P (1)
#define PIN_IMU1_INT        GPIO_NUM_6
#define PIN_IMU2_CS         GPIO_NUM_9     // ICM-42688-P (2)
#define PIN_IMU2_INT        GPIO_NUM_10

// --- I2C Bus (Magnetometer & Haptics) ---
#define PIN_I2C_SDA         GPIO_NUM_7     // MMC5983MA + DRV2605L
#define PIN_I2C_SCL         GPIO_NUM_8

// --- USB & Serial ---
#define PIN_USB_DM          GPIO_NUM_19    // Native USB D-
#define PIN_USB_DP          GPIO_NUM_20    // Native USB D+
#define PIN_UART0_TX        GPIO_NUM_43    // H1 TX / U0TXD
#define PIN_UART0_RX        GPIO_NUM_44    // H1 RX / U0RXD