import time
from rich.console import Console
from .core import disparar_e_aguardar

Console = Console()

def bateria_rate_sensitivity(ep, acc, destino, operadora, ramal, painel, sip_domain,
                               intervalos=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
                               chamadas_por_intervalo=10, cooldown_s=120):
    for intervalo in intervalos:
        bloco_id = f"{destino}_{operadora}_{intervalo}s_{int(time.time())}"
        Console.print(f"\n[bold magenta]--- Rate test: {operadora}/{destino} @ {intervalo}s ---")

        for i in range(chamadas_por_intervalo):
            call = disparar_e_aguardar(
                ep, acc, operadora, destino, ramal, painel, sip_domain,
                tipo_teste="rate_sensitivity",
                meta_extra={"intervalo_testado_s": intervalo, "bloco_id": bloco_id, "seq": i + 1},
            )
            if call:
                Console.print(f"    chamada {i+1}/{chamadas_por_intervalo}: {call.last_status_code}")
            time.sleep(intervalo)

        Console.print(f"[bold magenta]Cooldown de {cooldown_s}s antes do próximo intervalo...")
        time.sleep(cooldown_s)