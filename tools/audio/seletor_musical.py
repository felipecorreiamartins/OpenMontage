import json
import random
import sys
from pathlib import Path

catalogo = Path(r"D:\YouTube-Automacao\Musicas\catalogo_musical.json")
musicas = json.loads(catalogo.read_text(encoding="utf-8"))

def selecionar_musica(emocao):
    candidatas = [
        musica for musica in musicas
        if emocao.lower() in musica.get("humor", [])
        and Path(musica["arquivo"]).is_file()
    ]

    if not candidatas:
        return None

    return random.choice(candidatas)

if __name__ == "__main__":
    emocao = sys.argv[1].lower() if len(sys.argv) > 1 else "suspense"
    resultado = selecionar_musica(emocao)

    if resultado:
        print("Emocao solicitada:", emocao)
        print("Musica selecionada:", resultado["nome"])
        print("Arquivo:", resultado["arquivo"])
        print("Classificacoes:", ", ".join(resultado["humor"]))
    else:
        print("Nenhuma musica encontrada para:", emocao)
