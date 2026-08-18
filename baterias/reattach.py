# baterias/reattach.py
import time
from rich.console import Console
from .core import disparar_e_aguardar

Console = Console()


def bateria_reattach_manual(ep, acc, destino, operadora, ramal, painel, sip_domain,
                              intervalo_sondagem=1, tempo_max_sondagem=90,
                              ciclo_atual=None, ciclo_total=None):
    """
    Testa o comportamento SIP durante o ciclo de reattach à rede:
    baseline -> modo avião -> sondagem pós-reativação até voltar 200 OK.

    Retorna True se o ciclo foi concluído, False se foi pulado pelo usuário.
    """
    bloco_id = f"reattach_{destino}_{operadora}_{int(time.time())}"

    progresso = f" [{ciclo_atual}/{ciclo_total}]" if ciclo_atual and ciclo_total else ""
    Console.print(f"\n[bold yellow]--- Teste de reattach{progresso}: {operadora}/{destino} ---")

    # 1. Baseline
    Console.print("[bold yellow]Baseline: discando com celular normal")
    call_base = disparar_e_aguardar(
        ep, acc, operadora, destino, ramal, painel, sip_domain,
        tipo_teste="reattach",
        meta_extra={"fase": "baseline", "bloco_id": bloco_id},
    )
    if call_base:
        Console.print(f"    baseline: {call_base.last_status_code} ({call_base.last_status_text})")

    # 2. Modo avião — com opção de pular o ciclo
    resp = input("\n>>> Ative o modo avião e pressione ENTER (ou 's' pra pular este ciclo)... ")
    if resp.strip().lower() == 's':
        Console.print(f"[yellow]Ciclo {operadora}/{destino} pulado pelo usuário.[/yellow]")
        return False

    Console.print("[bold yellow]Discando com celular em modo avião")
    call_aviao = disparar_e_aguardar(
        ep, acc, operadora, destino, ramal, painel, sip_domain,
        tipo_teste="reattach",
        meta_extra={"fase": "modo_aviao", "bloco_id": bloco_id},
    )
    if call_aviao:
        Console.print(f"    modo avião: {call_aviao.last_status_code} ({call_aviao.last_status_text})")

    # 3. Desativação — também pulável, caso algo trave
    resp = input("\n>>> Desative o modo avião e pressione ENTER IMEDIATAMENTE (ou 's' pra pular)... ")
    if resp.strip().lower() == 's':
        Console.print(f"[yellow]Sondagem de {operadora}/{destino} pulada pelo usuário.[/yellow]")
        return False

    t0 = time.time()
    Console.print("[bold yellow]Iniciando sondagem de reattach...")

    reatachou = False
    while time.time() - t0 < tempo_max_sondagem:
        delta = round(time.time() - t0, 2)

        call = disparar_e_aguardar(
            ep, acc, operadora, destino, ramal, painel, sip_domain,
            tipo_teste="reattach",
            meta_extra={"fase": "sondagem", "bloco_id": bloco_id, "t_apos_desativar_s": delta},
        )

        if call:
            Console.print(f"    t+{delta}s: {call.last_status_code} ({call.last_status_text})")
            if call.last_status_code == 200:
                Console.print(f"[bold green]Reatachado — primeiro 200 OK em t+{delta}s")
                reatachou = True
                break

        time.sleep(intervalo_sondagem)

    if not reatachou:
        Console.print(f"[bold red]Não reatachou dentro do tempo máximo de sondagem ({tempo_max_sondagem}s)")

    Console.print(f"[bold yellow]--- Fim do ciclo (bloco {bloco_id}) ---\n")
    return True