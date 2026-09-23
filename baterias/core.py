import time
import pjsua2 as pj
from rich.console import Console
from teste import TesteCall, numero_discagem

Console = Console()

def disparar_e_aguardar(ep, acc, operadora, destino, ramal, painel, sip_domain,
                          tipo_teste="padrao", meta_extra=None):
    numero_final = numero_discagem(operadora, destino)

    call = TesteCall(
        acc=acc, call_id=pj.PJSUA_INVALID_ID,
        operadora=operadora, telefone=destino,
        ip=sip_domain, ramal=ramal, painel=painel,
    )
    call.tipo_teste = tipo_teste
    call.meta_extra = meta_extra or {}

    call_prm = pj.CallOpParam(True)
    dst_uri = f"sip:{numero_final}@{sip_domain}"

    try:
        call.makeCall(dst_uri, call_prm)
    except pj.Error as e:
        Console.print(f"[bold red]Erro ao disparar makeCall para {dst_uri}: {e.info()}")
        return None

    while True:
        try:
            ep.libHandleEvents(50)
            if call.getInfo().state >= pj.PJSIP_INV_STATE_DISCONNECTED:
                break
        except Exception as err:
            Console.print(f"[bold yellow]Exceção no monitoramento da chamada: {err}")
            break

    return call