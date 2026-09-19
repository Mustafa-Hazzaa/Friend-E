from venv import logger

class MockArduinoDevice:

    def __init__(self):
        self.battery_level = "75"   # fake battery so the UI shows something

    def connect(self, port="") -> bool:
        logger.info(f"[MOCK] connect({port})")
        return True

    def disconnect(self) -> None:
        logger.info("[MOCK] disconnect")

    def is_connected(self) -> bool:
        return True

    def send(self, cmd: str) -> bool:
        logger.info(f"[MOCK] send → {cmd}")
        return True

    def _parse(self, msg): pass

arduino = MockArduinoDevice()\
