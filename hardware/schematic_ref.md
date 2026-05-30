# Space Drums 2.0 — Schematic Reference Manual

This document serves as the technical reference for the Space Drums 2.0 printed circuit board schematic configuration. It inventories all integrated circuits, component blocks, communication buses, and hardware net structures.

---

## 1. Primary Integrated Circuit Inventory

| Reference Designator | Component Part Number | Manufacturer | Primary Function / Description |
| :--- | :--- | :--- | :--- |
| **U1** | ESP32-S3-MINI-1-N8 | Espressif Systems | Main Microcontroller Module (Wi-Fi/Bluetooth) |
| **U4** | ICM-42688-P | TDK InvenSense | 6-Axis Inertial Measurement Unit (Secondary) |
| **U5** | ICM-42688-P | TDK InvenSense | 6-Axis Inertial Measurement Unit (Primary) |
| **U7** | DRV2605L | Texas Instruments | Haptic Driver for ERM/LRA Actuators |
| **U8** | MMC5983MA | MEMSIC | 3-Axis Anisotropic Magnetometer (Compass) |
| **U10** | LTC2954 | Analog Devices | Pushbutton Power Benefit Controller |

---

## 2. Bus Architecture and Signal Routing

### 2.1 High-Speed Serial Peripheral Interface (SPI) Bus
The primary motion tracking sensors share a high-speed SPI bus to stream sensor data to the ESP32-S3 module.

* **Master Out Slave In (`SPI_MOSI`):** Routed to ESP32 pin **GPIO35**. Connects to Pin 13 (`SDI`) on U4 and U5.
* **Master In Slave Out (`SPI_MISO`):** Routed to ESP32 pin **GPIO37**. Connects to Pin 12 (`SDO`) on U4 and U5.
* **Serial Clock (`SPI_SCK`):** Routed to ESP32 pin **GPIO36**. Connects to Pin 11 (`SCLK`) on U4 and U5.

#### Dedicated Control Lines
* **U5 (IMU 1) Chip Select (`IMU1_CS`):** Routed to ESP32 pin **GPIO5**.
* **U5 (IMU 1) Hardware Interrupt (`IMU1_INT`):** Routed to ESP32 pin **GPIO6**.
* **U4 (IMU 2) Chip Select (`IMU2_CS`):** Routed to ESP32 pin **GPIO9**.
* **U4 (IMU 2) Hardware Interrupt (`IMU2_INT`):** Routed to ESP32 pin **GPIO10**.

### 2.2 Inter-Integrated Circuit (I2C) Bus
Auxiliary configuration, orientation, and haptic feedback devices share a standard I2C bus.

* **Serial Data (`SDA`):** Routed to ESP32 pin **GPIO7**. Connects to U7 (`SDA`) and U8 (`SDA`).
* **Serial Clock (`SCL`):** Routed to ESP32 pin **GPIO8**. Connects to U7 (`SCL`) and U8 (`SCL`).

#### Specific Hardware Configurations
* **U8 Magnetometer Interrupt:** The hardware interrupt pin on the MMC5983MA chip is unrouted in this schematic revision.
* **U7 Haptic Driver Trigger Mode:** The `IN/TRIG` pin on the DRV2605L chip is tied directly to system ground. Waveform playback execution is commanded entirely through software register writes over the I2C interface.

---

## 3. Power Control and Monitoring Architecture

### 3.1 Intelligent Power State Engine
The U10 LTC2954 controller handles system boot and power-down states via an external physical pushbutton interface.

* **Power Hold Signal (`KILL`):** Driven by ESP32 pin **GPIO11**. Must be asserted by firmware immediately during boot execution to lock the power delivery circuitry into an active state.
* **Power Warning Interrupt (`INT`):** Routed to ESP32 pin **GPIO12**. The U10 controller asserts this signal low when the physical power button is pressed, indicating that a shutdown sequence is requested.

### 3.2 Analogue Battery Measurement
The state-of-charge tracking mechanism monitors the lithium-ion polymer battery cells safely.

* **Battery Voltage Monitor (`VBAT_SENSE`):** Routed to ESP32 pin **GPIO4** (configured as an Analog-to-Digital Converter channel). 
* **Voltage Division Structure:** Resistors R9 and R10 form a scaling network, partnered with smoothing capacitor C21, to bring raw battery voltages down to safe operating limits for the microcontroller input pin.

---

## 4. Input, Output, and Interface Routing

### 4.1 Native USB Interface
* **USB Data Negative (`USB_D-`):** Routed through a protective series resistor inline to ESP32 pin **GPIO19**.
* **USB Data Positive (`USB_D+`):** Routed through a protective series resistor inline to ESP32 pin **GPIO20**.

### 4.2 Hardware User Interface
* **Boot Selection Mode:** Handled via manual tactile pushbutton SW2 and pull-up configuration resistor R5 connected directly to net `IO0` (ESP32 pin **GPIO0**).
* **Hardware Chip Reset:** Handled via manual tactile pushbutton SW1 connected directly to the `EN` pin of the ESP32 module, decoupled via the resistor-capacitor combination of R6 and C5.
* **Status Output Indication:** Driven by ESP32 pin **GPIO41** through current-limiting resistor R18 directly to the active-high status light-emitting diode designated as LED1.
