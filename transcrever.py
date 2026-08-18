# -*- coding: utf-8 -*-
# transcrever_standalone.py
import sys
import json
import whisper

def processar_audio(caminho_wav):
    modelo = whisper.load_model("base")
    resultado = modelo.transcribe(caminho_wav, language="pt")
    return resultado.get("text", "")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"erro": "Caminho do arquivo não fornecido"}))
        sys.exit(1)
        
    caminho_audio = sys.argv[1]
    texto = processar_audio(caminho_audio)
    print(json.dumps({"texto": texto}))