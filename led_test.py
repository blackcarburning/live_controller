import time
import serial
from serial.tools import list_ports

BAUD = 9600
TARGET_ID = "LED_TEST_PRO_MINI_01"
PROBE_CMD = b'?\n'

def probe_port(port_name, baud=BAUD, timeout=1.2):
    try:
        with serial.Serial(port_name, baud, timeout=timeout) as ser:
            time.sleep(2.0)
            ser.reset_input_buffer()
            ser.write(PROBE_CMD)
            ser.flush()
            time.sleep(0.3)

            lines = []
            end_time = time.time() + timeout
            while time.time() < end_time:
                if ser.in_waiting:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line:
                        lines.append(line)

            if lines:
                return lines[-1]
            return None
    except Exception:
        return None

def find_target_ports():
    matches = []

    for port in list_ports.comports():
        identity = probe_port(port.device)
        if identity == TARGET_ID:
            matches.append(port)

    return matches

def choose_port():
    matches = find_target_ports()

    if not matches:
        print(f'No board found with identity "{TARGET_ID}"')
        return None

    if len(matches) == 1:
        port = matches[0].device
        print(f'Found {TARGET_ID} on {port}')
        return port

    print(f'Multiple boards found with identity "{TARGET_ID}":\n')
    for i, port in enumerate(matches, start=1):
        print(f"{i}. {port.device} - {port.description or 'Unknown device'}")

    while True:
        choice = input(f"Select port [1-{len(matches)}] or q to quit: ").strip().lower()

        if choice == "q":
            return None

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                return matches[idx].device

        print("Invalid selection.")

def show_menu():
    print("\nLED Test Menu")
    print("1 - Turn on LED 1")
    print("2 - Turn on LED 2")
    print("3 - Turn on LED 3")
    print("4 - Turn all LEDs off")
    print("5 - Run chase test")
    print("q - Quit")

def main():
    port = choose_port()
    if not port:
        return

    try:
        ser = serial.Serial(port, BAUD, timeout=1)
        time.sleep(2)
        print(f"Connected to {TARGET_ID} on {port}")
    except Exception as e:
        print(f"Could not open {port}: {e}")
        return

    try:
        while True:
            show_menu()
            choice = input("Choose an option: ").strip().lower()

            if choice == "q":
                print("Exiting.")
                break

            if choice in ["1", "2", "3", "4", "5"]:
                ser.write(choice.encode("utf-8"))
                time.sleep(0.2)

                while ser.in_waiting:
                    response = ser.readline().decode(errors="ignore").strip()
                    if response:
                        print(f"Board: {response}")
            else:
                print("Invalid choice.")
    finally:
        ser.close()
        print("Serial port closed.")

if __name__ == "__main__":
    main()
