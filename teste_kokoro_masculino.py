import time
import soundfile as sf
from kokoro import KPipeline

inicio = time.perf_counter()

print("Carregando Kokoro...")
pipeline = KPipeline(lang_code="a")
carregamento = time.perf_counter()

texto = "Welcome to the future of technology. Today, we will explore how artificial intelligence is changing our world."

print("Gerando voz masculina...")
partes = []
for _, _, audio in pipeline(texto, voice="am_michael"):
    partes.append(audio)

import numpy as np
audio_final = np.concatenate(partes)

sf.write("teste_kokoro_masculino.wav", audio_final, 24000)

print("Tempo de carregamento:", round(carregamento - inicio, 1), "segundos")
print("Tempo de geracao:", round(time.perf_counter() - carregamento, 1), "segundos")
print("Audio salvo!")
