from queue import Queue, Empty
from threading import Thread, Event
from serial import Serial
import serial.tools.list_ports
import time


class ArduinoDevice:

    def __init__(self):
        self.queue = Queue()
        self.exit_flag = Event()
        self.port_name = ""
        self.serial_port = None
        self.serial_thread = None
        self.battery_level = None
        self.exit_flag.clear()

    def connect(self, port=""):
        usb_ports = [p.device for p in serial.tools.list_ports.comports()]
        print(usb_ports)

        if isinstance(port, str) and port == "":
            port = self.port_name

        if isinstance(port, int):
            port = usb_ports[port]

        if port in usb_ports:
            self.disconnect()

            self.serial_port = Serial(port, 115200)
            self.serial_port.flushInput()
            self.port_name = port

            self.exit_flag.clear()
            self.serial_thread = Thread(target=self.__communication_thread, daemon=True)
            self.serial_thread.start()

        return self.is_connected()

    def disconnect(self):
        self.exit_flag.set()

        if self.serial_thread:
            self.serial_thread.join(timeout=1)

        if self.serial_port:
            try:
                self.serial_port.close()
            except:
                pass

        self.serial_thread = None
        self.serial_port = None

    def send_command(self, command: str) -> bool:
        if self.is_connected():
            self.queue.put(command)
            return True
        return False
        return False

    def is_connected(self):
        return (
            self.serial_thread is not None and self.serial_thread.is_alive()
            and self.serial_port is not None and self.serial_port.is_open
        )

    def __communication_thread(self):
        dataString = ""

        while not self.exit_flag.is_set():
            try:
                try:
                    data = self.queue.get(timeout=0.1)
                    self.serial_port.write((data + '\n').encode())
                except Empty:
                    pass

            except Exception as ex:
                pass

            time.sleep(0.01)