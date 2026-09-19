# import serial
# import time


# class MotorController:
#     def __init__(self, port="/dev/ttyA", baud=115200):
#         self.arduino = serial.Serial(port, baud, timeout=1)
#         time.sleep(4)
#         print("MotorController ready")

#     def get_distance(self):
#         """
#         Request distance from Arduino and read the response.
#         """
#         # Clear the serial buffer first
#         self.arduino.reset_input_buffer()

#         self.arduino.write(b"REQ\n")
#         self.arduino.flush()  # Wait until all data is written

#         start_time = time.time()
#         timeout = 2

#         while time.time() - start_time < timeout:
#             line = self.arduino.readline().decode('utf-8').strip()

#             if line:
#                 try:
#                     distance = int(line)
#                     return distance
#                 except ValueError:
#                     # Ignore non-distance messages
#                     pass

#             time.sleep(0.01)

#         return None

#     def send_action(self, command):
#         """
#         Send motor command to Arduino and wait for DONE.
#         """
#         # Clear the serial buffer first
#         self.arduino.reset_input_buffer()

#         # Send command with newline
#         full_command = command + "\n"
#         self.arduino.write(full_command.encode())
#         self.arduino.flush()  # Ensure command is sent

#         print(f"Sent: '{full_command.strip()}'")  # Debug

#         start_time = time.time()
#         timeout = 10

#         while time.time() - start_time < timeout:
#             if self.arduino.in_waiting > 0:
#                 line = self.arduino.readline().decode('utf-8').strip()
#                 print(f"Received from Arduino: '{line}'")  # Debug

#                 if line == "DONE":
#                     print(f"Action {command.split(',')[0]} complete")
#                     return
#                 elif line:
#                     # Print any other messages
#                     print(f"Arduino: {line}")
#             time.sleep(0.05)

#         print(f"Warning: Action {command.split(',')[0]} timed out!")