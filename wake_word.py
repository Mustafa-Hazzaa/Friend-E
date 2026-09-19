import pyaudio
import numpy as np
import time
from openwakeword.model import Model

CHUNK = 1280
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
WAKE_WORD = "hey_jarvis"
THRESHOLD = 0.6
COOLDOWN = 1.0


def listen_for_wake_word(detected_callback):
    model = Model(wakeword_models=[WAKE_WORD], inference_framework="onnx")

    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )


    last_detected = 0

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)

            prediction = model.predict(audio_data)
            score = prediction.get(WAKE_WORD, 0)

            now = time.time()
            if score >= THRESHOLD and (now - last_detected) > COOLDOWN:
                last_detected = now
                detected_callback()

    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()