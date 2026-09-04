#include <esp_now.h>
#include <WiFi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// --- Foot pedals: momentary switch from pin to GND, internal pull-up ---
const int PIN_PEDAL_LEFT  = 1;   // XIAO D0 / GPIO1
const int PIN_PEDAL_RIGHT = 2;   // XIAO D1 / GPIO2
const int PEDAL_PINS[2]   = {PIN_PEDAL_LEFT, PIN_PEDAL_RIGHT};
const uint32_t PEDAL_DEBOUNCE_MS = 8;  // report the first edge, then ignore contact bounce
const uint8_t  PEDAL_VELOCITY    = 6;  // plain switches, no velocity sensing

// Both edges are reported now: in hi-hat mode the PC uses the held state to
// pick hihat_closed.wav vs hihat_open.wav for stick hits.
bool     pedalPressed[2]   = {false, false};
uint32_t pedalChangedMs[2] = {0, 0};

// Must match StickPacket in spacedrums_2.ino byte for byte.
// The sticks only ever send MSG_HIT / MSG_BATTERY; pedals are read here.
enum : uint8_t { MSG_HIT = 0, MSG_BATTERY = 1, MSG_PEDAL = 2 };
typedef struct __attribute__((packed)) struct_message {
    uint8_t  type;
    uint8_t  stick_id;
    uint8_t  drum_id;
    uint8_t  velocity;
    uint8_t  battery_pct;
    uint16_t battery_mv;
} struct_message;

// Create a queue to hold up to 20 rapid-fire hits
QueueHandle_t hubQueue;

// Polled instead of interrupt-driven: a bouncing contact can no longer latch
// the wrong open/closed state, the next poll re-reads the settled level.
void pollPedals() {
    uint32_t now = millis();
    for (uint8_t i = 0; i < 2; i++) {
        bool pressed = (digitalRead(PEDAL_PINS[i]) == LOW);
        if (pressed == pedalPressed[i]) continue;
        if (now - pedalChangedMs[i] < PEDAL_DEBOUNCE_MS) continue;

        pedalChangedMs[i] = now;
        pedalPressed[i] = pressed;

        Serial.print("P,");
        Serial.print(i);
        Serial.print(",");
        Serial.print(PEDAL_VELOCITY);
        Serial.print(",");
        Serial.println(pressed ? 1 : 0);
    }
}

// ESP32 Core v3.x Callback
void OnDataRecv(const esp_now_recv_info *info, const uint8_t *incomingData, int len) {
    if (len != (int)sizeof(struct_message)) return;
    struct_message hit;
    memcpy(&hit, incomingData, sizeof(hit));
    
    // OFF-LOAD TO QUEUE INSTANTLY! DO NOT SERIAL.PRINT HERE!
    // This frees the Wi-Fi stack in ~1 microsecond to catch the other stick's packet.
    xQueueSend(hubQueue, &hit, 0);
}

void setup() {
    // 80 MHz is the Wi-Fi minimum and leaves the 80 MHz APB clock (and the UART
    // baud rate) untouched, but runs the board noticeably cooler.
    setCpuFrequencyMhz(80);

    Serial.begin(500000);
    WiFi.mode(WIFI_STA);

    // Initialize the FreeRTOS Queue
    hubQueue = xQueueCreate(20, sizeof(struct_message));

    pinMode(PIN_PEDAL_LEFT, INPUT_PULLUP);
    pinMode(PIN_PEDAL_RIGHT, INPUT_PULLUP);

    delay(2000);
    Serial.print("HUB MAC ADDRESS: ");
    Serial.println(WiFi.macAddress());

    if (esp_now_init() != ESP_OK) {
        Serial.println("Error initializing ESP-NOW");
        return;
    }
    
    esp_now_register_recv_cb(OnDataRecv);
}

void loop() {
    struct_message pkt;

    // Wake at least once per tick so the pedals are polled promptly, but return
    // instantly whenever a stick packet is waiting.
    if (xQueueReceive(hubQueue, &pkt, pdMS_TO_TICKS(1)) == pdPASS) {
        // Safe to take our time printing here, the Wi-Fi task is untouched
        if (pkt.type == MSG_HIT) {
            Serial.print("H,");
            Serial.print(pkt.stick_id);
            Serial.print(",");
            Serial.print(pkt.drum_id);
            Serial.print(",");
            Serial.println(pkt.velocity);
        } else if (pkt.type == MSG_BATTERY) {
            Serial.print("B,");
            Serial.print(pkt.stick_id);
            Serial.print(",");
            Serial.print(pkt.battery_pct);
            Serial.print(",");
            Serial.println(pkt.battery_mv);
        }
    }

    pollPedals();
}