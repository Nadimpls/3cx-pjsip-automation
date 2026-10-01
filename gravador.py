import csv
import os
import time
import pjsua2 as pj
from rich.console import Console

console = Console()

wav_writer = None


def _media_de_audio(call):
    call_info = call.getInfo()
    for media_idx in range(len(call_info.media)):
        if call_info.media[media_idx].type == pj.PJMEDIA_TYPE_AUDIO:
            return pj.AudioMedia.typecastFromMedia(call.getMedia(media_idx))
    return None


def iniciar_gravacao(call, file_path="gravacao_chamada.wav", target_folder="./audios"):
    global wav_writer
    try:
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)

        full_path = os.path.join(target_folder, file_path)

        wav_writer = pj.AudioMediaRecorder()
        wav_writer.createRecorder(full_path)


        time.sleep(0.5)

        call_media = _media_de_audio(call)

        if call_media:
            call_media.startTransmit(wav_writer)
            print(f"GRAVANDO CHAMADA COM SUCESSO EM: {full_path}")
        else:
            print("NENHUMA MIDIA DE AUDIO ENCONTRADA NA CHAMADA")

    except pj.Error as err:
        print(f"Erro ao iniciar gravação: {err.info().reason}")
    except Exception as e:
        print(f"Erro inesperado ao iniciar gravação: {e}")


def reconectar_gravacao(call):
    global wav_writer
    if wav_writer is None:
        return
    try:
        call_media = _media_de_audio(call)
        if call_media:
            call_media.startTransmit(wav_writer)
    except pj.Error:
        pass
    except Exception:
        pass

def parar_gravacao(call):
    global wav_writer
    if not wav_writer:
        return

    try:
        try:
            call_info = call.getInfo()
            call_media = None
            for media_idx in range(len(call_info.media)):
                if call_info.media[media_idx].type == pj.PJMEDIA_TYPE_AUDIO:
                    call_media = call.getMedia(media_idx)
                    call_media = pj.AudioMedia.typecastFromMedia(call_media)
                    break

            if call_media:
                call_media.stopTransmit(wav_writer)
        except Exception:
            pass  


        try:
            wav_writer.delete()
        except Exception:
            pass

        print("GRAVAÇÃO FINALIZADA COM SUCESSO")


    except Exception as err:
        print(f"ERRO AO PARAR A GRAVAÇÃO: {err}")
    finally:
        wav_writer = None