import serial
import struct
import time
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt

# ---------------- Serial configuration ----------------
SERIAL_PORT = "COM6"      # <-- change to your port, e.g. COM3 / COM5 / ...
BAUD_RATE = 115200
START_BYTE = 0x9A

# Packet layout must match the ESP32 "SerialOutPacket" struct:
# struct __attribute__((packed)) SerialOutPacket {
#   int16_t roll_deg_x100;
#   int16_t pitch_deg_x100;
#   int16_t yaw_deg_x100;
#   int16_t reserved1;
#   int16_t reserved2;
#   int16_t gyro_x_deg_s_x10;
#   int16_t gyro_y_deg_s_x10;
#   int16_t gyro_z_deg_s_x10;
#   int16_t acc_x_g_x1000;
#   int16_t acc_y_g_x1000;
#   int16_t acc_z_g_x1000;
#   uint8_t checksum;
# };
FORMAT_OUT = "<3h2h6hB"
SIZE_OUT = struct.calcsize(FORMAT_OUT)  # should be 23 bytes

# How many samples to record before saving/plotting
MAX_SAMPLES = 5000  # ~50 seconds at 100 Hz; change as you like


def calc_checksum(data_bytes: bytes) -> int:
    """Sum of all bytes mod 256."""
    s = 0
    for b in data_bytes:
        s = (s + b) & 0xFF
    return s


def read_one_frame(ser: serial.Serial):
    """
    Read one valid frame from the serial stream.
    Frame format: [0x9A][payload(23 bytes)]
    Returns unpacked tuple or None if timeout.
    """
    # Find start byte
    while True:
        b = ser.read(1)
        if not b:
            return None  # timeout
        if b[0] == START_BYTE:
            break

    # Read payload
    payload = ser.read(SIZE_OUT)
    if len(payload) != SIZE_OUT:
        return None

    # Check checksum: last byte is checksum
    data = payload[:-1]
    recv_checksum = payload[-1]
    calc = calc_checksum(data)

    if calc != recv_checksum:
        # Bad frame, discard
        print(f"[WARN] Checksum mismatch: calc={calc}, recv={recv_checksum}")
        return None

    # Unpack int16/uint8 values
    return struct.unpack(FORMAT_OUT, payload)


def main():
    print(f"Opening {SERIAL_PORT} @ {BAUD_RATE}...")
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1.0)
    time.sleep(2.0)  # give ESP32 some time to boot

    rows = []

    print("Start logging IMU + attitude data. Press Ctrl+C to stop.")
    try:
        while len(rows) < MAX_SAMPLES:
            frame = read_one_frame(ser)
            if frame is None:
                continue

            (
                roll_x100,
                pitch_x100,
                yaw_x100,
                reserved1,
                reserved2,
                gyro_x_x10,
                gyro_y_x10,
                gyro_z_x10,
                acc_x_x1000,
                acc_y_x1000,
                acc_z_x1000,
                _checksum,
            ) = frame

            # Convert back to physical units
            roll_deg = roll_x100 / 100.0
            pitch_deg = pitch_x100 / 100.0
            yaw_deg = yaw_x100 / 100.0

            gyro_x_deg_s = gyro_x_x10 / 10.0
            gyro_y_deg_s = gyro_y_x10 / 10.0
            gyro_z_deg_s = gyro_z_x10 / 10.0

            acc_x_g = acc_x_x1000 / 1000.0
            acc_y_g = acc_y_x1000 / 1000.0
            acc_z_g = acc_z_x1000 / 1000.0

            ts = datetime.now().isoformat()

            rows.append(
                {
                    "timestamp": ts,
                    "roll_deg": roll_deg,
                    "pitch_deg": pitch_deg,
                    "yaw_deg": yaw_deg,
                    "gyro_x_deg_s": gyro_x_deg_s,
                    "gyro_y_deg_s": gyro_y_deg_s,
                    "gyro_z_deg_s": gyro_z_deg_s,
                    "acc_x_g": acc_x_g,
                    "acc_y_g": acc_y_g,
                    "acc_z_g": acc_z_g,
                }
            )

            # Print every 50 samples
            if len(rows) % 50 == 0:
                print(
                    f"[{len(rows):4d}] "
                    f"R={roll_deg:6.2f} P={pitch_deg:6.2f} Y={yaw_deg:6.2f} | "
                    f"Gx={gyro_x_deg_s:7.3f} Gy={gyro_y_deg_s:7.3f} Gz={gyro_z_deg_s:7.3f} | "
                    f"Ax={acc_x_g:7.3f} Ay={acc_y_g:7.3f} Az={acc_z_g:7.3f}"
                )

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt: stopping logging...")

    finally:
        ser.close()
        print("Serial port closed.")

    if not rows:
        print("No data recorded.")
        return

    # Save to CSV
    df = pd.DataFrame(rows)
    csv_name = "imu_log.csv"
    df.to_csv(csv_name, index=False)
    print(f"Saved {len(df)} samples to {csv_name}")

    # Simple plots: roll/pitch/yaw and gyro X/Y/Z
    try:
        # use sample index as x-axis
        x = range(len(df))

        plt.figure()
        plt.title("Attitude (deg)")
        plt.plot(x, df["roll_deg"], label="roll")
        plt.plot(x, df["pitch_deg"], label="pitch")
        plt.plot(x, df["yaw_deg"], label="yaw")
        plt.xlabel("Sample index")
        plt.ylabel("deg")
        plt.legend()

        plt.figure()
        plt.title("Gyro (deg/s)")
        plt.plot(x, df["gyro_x_deg_s"], label="gx")
        plt.plot(x, df["gyro_y_deg_s"], label="gy")
        plt.plot(x, df["gyro_z_deg_s"], label="gz")
        plt.xlabel("Sample index")
        plt.ylabel("deg/s")
        plt.legend()

        plt.show()
    except Exception as e:
        print(f"Plotting error: {e}")


if __name__ == "__main__":
    main()
