# -*- coding: utf-8 -*-
import contextlib
import json
import os
import subprocess
import sys
import unicodedata
import wave

# Caminho do executável do Python dentro do venv_win
PYTHON_VENV = (
    r"C:\Users\80145020940\Documents\Automocao_3CX\venv_win\Scripts\python.exe"
)

# Termos comuns em caixas postais, URA e mensagens de rede no Brasil (sem acentos)
TERMOS_CAIXA_POSTAL = [
    "desculpa",
    "desculpe",
    "desculpe nos",
    "nao foi possivel",
    "caixa postal",
    "recado",
    "deixe seu recado",
    "sinal sonoro",
    "bip",
    "encaminhada",
    "nao esta disponivel",
    "nao pode atender",
    "fora de area",
    "desligado",
    "numero discado",
    "atender no momento",
    "voicemail",
]

CODIGOS_OCUPADO_REJEITADA = {486, 600, 603}
CODIGOS_FALHA = {404, 484, 502, 503, 504}


def remover_acentos(texto: str) -> str:
  """Remove acentos, pontuações e converte para minúsculas."""
  if not texto:
    return ""
  nfkd_form = unicodedata.normalize("NFKD", texto)
  texto_sem_acento = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
  return texto_sem_acento.lower().strip()


def duracao_audio_segundos(wav_path: str):
  """Retorna a duração total do arquivo WAV em segundos."""
  if not wav_path or not os.path.exists(wav_path):
    return None
  try:
    with contextlib.closing(wave.open(wav_path, "rb")) as wf:
      frames = wf.getnframes()
      rate = wf.getframerate()
      if rate <= 0:
        return None
      return round(frames / float(rate), 2)
  except Exception:
    return None


def transcrever_audio_via_subprocess(wav_path: str) -> str:
  """Executa o Whisper de forma isolada dentro do Python do venv_win."""
  print(f"\n[WHISPER] 🎙️ Transcrevendo áudio: {wav_path}...")

  script_code = f"""
import whisper
import json
try:
    modelo = whisper.load_model("base")
    resultado = modelo.transcribe(r"{wav_path}", language="pt", fp16=False)
    print(json.dumps({{"texto": resultado.get("text", "").strip()}}))
except Exception as e:
    print(json.dumps({{"erro": str(e)}}))
"""
  try:
    resultado = subprocess.run(
        [PYTHON_VENV, "-c", script_code],
        capture_output=True,
        text=True,
        check=True,
    )
    dados = json.loads(resultado.stdout)
    texto = dados.get("texto", "")
    print(f"[WHISPER] ✅ Transcrição: '{texto}'")
    return texto
  except Exception as e:
    print(f"[WHISPER] ❌ Erro na transcrição: {e}")
    return ""


def analisar_conteudo_audio(wav_path: str) -> dict:
  """Transcreve e analisa se a mensagem é caixa postal ou voz humana."""
  if not wav_path or not os.path.exists(wav_path):
    return {
        "is_voicemail": False,
        "texto": "",
        "motivo": "Arquivo de áudio não encontrado",
    }

  try:
    texto_original = transcrever_audio_via_subprocess(wav_path)
    texto_limpo = remover_acentos(texto_original)

    if not texto_limpo:
      return {
          "is_voicemail": False,
          "texto": "",
          "motivo": "Silêncio ou áudio sem fala compreensível",
      }

    palavras = texto_limpo.split()

    # 1. Regra Prioritária: Se começar com pedido de desculpas, é mensagem automática de rede/caixa postal
    primeiras_palavras = " ".join(palavras[:3])
    if any(p in primeiras_palavras for p in ["desculpa", "desculpe", "desculpem"]):
      return {
          "is_voicemail": True,
          "texto": texto_original,
          "motivo": (
              "Mensagem de rede iniciada com pedido de desculpas"
              f" ('{primeiras_palavras}')"
          ),
      }

    # 2. Procura por palavras-chave na transcrição normalizada
    for termo in TERMOS_CAIXA_POSTAL:
      termo_limpo = remover_acentos(termo)
      if termo_limpo in texto_limpo:
        return {
            "is_voicemail": True,
            "texto": texto_original,
            "motivo": f"Detectado termo de caixa postal: '{termo}'",
        }

    # 3. Heurística de apoio: Fala curta com palavras institucionais
    duracao = duracao_audio_segundos(wav_path)
    if duracao and duracao <= 15.0 and len(palavras) <= 8:
      if any(
          p in texto_limpo for p in ["chama", "atender", "momento", "favor"]
      ):
        return {
            "is_voicemail": True,
            "texto": texto_original,
            "motivo": f"Mensagem automática curta ({duracao}s)",
        }

    return {
        "is_voicemail": False,
        "texto": texto_original,
        "motivo": "Atendido por humano (sem padrões de caixa postal)",
    }

  except Exception as e:
    return {
        "is_voicemail": False,
        "texto": "",
        "motivo": f"Erro no processamento do áudio: {str(e)}",
    }


def classificar_chamada(call, audio_path: str = None):
  """Combina a análise SIP com a análise do áudio WAV."""
  status = getattr(call, "last_status_code", 0)
  audio_duration = duracao_audio_segundos(audio_path) if audio_path else None
  analise_audio = analisar_conteudo_audio(audio_path) if audio_path else None

  outcome = "INDEFINIDO"
  motivo = ""
  transcricao = analise_audio["texto"] if analise_audio else ""

  # 1. Tratamento de Erros/Rejeição SIP
  if status in CODIGOS_OCUPADO_REJEITADA:
    outcome = "OCUPADO_REJEITADA"
    motivo = f"SIP {status} (ocupado/rejeitada)"

  elif status in CODIGOS_FALHA:
    outcome = "FALHA"
    motivo = f"SIP {status} (falha de rede/número)"

  # 2. Chamada Atendida (200 OK) -> Decisão baseada no Whisper
  elif getattr(call, "t_answer", None) is not None:
    if analise_audio and analise_audio["is_voicemail"]:
      outcome = "CAIXA_POSTAL"
      motivo = analise_audio["motivo"]
    else:
      outcome = "ATENDIDA_HUMANO"
      if transcricao:
        motivo = f"Atendida por Humano (Fala: '{transcricao}')"
      else:
        motivo = "Atendida (Sem fala detectada)"

  # 3. Não Atendida
  else:
    outcome = "NAO_ATENDIDA"
    motivo = f"Desligou sem atender (último status SIP={status})"

  return {
      "classificacao": outcome,
      "motivo_classificacao": motivo,
      "transcricao": transcricao,
      "audio_duration_s": audio_duration,
  }