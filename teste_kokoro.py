from kokoro import KPipeline
import soundfile as sf
import numpy as np

pipeline = KPipeline(lang_code='a')

texto = "Welcome to the future of technology. Today, we will explore how artificial intelligence is changing our world."

generator = pipeline(texto, voice='af_heart', speed=1)

audios = []
for _, _, audio in generator:
    audios.append(audio)

sf.write("teste_kokoro.wav", np.concatenate(audios), 24000)
print("Narracao Kokoro criada com sucesso!")
