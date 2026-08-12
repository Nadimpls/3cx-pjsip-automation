import csv
import os
import time
from rich.console import Console
from rich.table import Table
from rich.live import Live

console = Console()

CAMPOS_CSV = [
    "timestamp", 
    "ramal", 
    "tronco", 
    "pdd_s", 
    "setup_time_s", 
    "sip_code", 
    "sip_reason", 
    "atendida", 
    "Número"
]

def registrar_resultado(self):
    pdd_s = None
    if self.t_invite and self.t_ring:
        # Subtrai o momento do ring menos o momento do invite, dando o valor em segundos
        pdd_s = round(self.t_ring - self.t_invite, 2)

    setup_s = None
    if self.t_invite and self.t_answer:
        setup_s = round(self.t_answer - self.t_invite, 2)

    row = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ramal": self.ramal,
        "tronco": self.operadora,
        "pdd_s": pdd_s,            # PDD em segundos
        "setup_time_s": setup_s,    # Tempo total de atendimento em segundos
        "sip_code": self.last_status_code,
        "sip_reason": self.last_status_text,
        "atendida": self.t_answer is not None,
        "Número": self.telefone
    }

    if self.painel:
        self.painel.registrar(row)


def montar_tabela(chamadas):
    tabela = Table(title="Monitor de Chamadas PJSIP ao Vivo")
    tabela.add_column("Horário")
    tabela.add_column("Ramal")
    tabela.add_column("Tronco")
    tabela.add_column("PDD (s)")
    tabela.add_column("Status SIP")
    tabela.add_column("Atendida")
    tabela.add_column("Número")

    for c in chamadas:
        cor = "green" if c.get("sip_code") == 200 else "red"
        tabela.add_row(
            str(c.get("timestamp", "")),
            str(c.get("ramal", "")),
            str(c.get("tronco", "")),
            str(c.get("pdd_s", "")),
            f"[{cor}]{c.get('sip_code', '')}[/{cor}]",
            str(c.get("atendida", "")),
            str(c.get("Número", ""))
        )
    return tabela


def salvar_csv(row, caminho="resultado_pdd.csv"):
    try:
        diretorio_atual = os.path.dirname(os.path.abspath(__file__))
        caminho_completo = os.path.join(diretorio_atual, caminho)

        arquivo_existe = os.path.exists(caminho_completo)

        with open(caminho_completo, "a", newline="", encoding="utf-8") as f:
            # Usa a lista padrão CAMPOS_CSV para manter a ordem correta das colunas
            writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
            if not arquivo_existe or f.tell() == 0:
                writer.writeheader()
            writer.writerow(row)
            
        console.print(f"[dim green][CSV] Linha salva com sucesso.[/dim green]")
        
    except Exception as e:
        console.print(f"[bold red][ERRO AO SALVAR CSV]: {e}[/bold red]")


class PainelAoVivo:
    """Mantém uma lista de chamadas e atualiza a tabela em tempo real."""

    def __init__(self):
        self.chamadas = []
        self.live = Live(montar_tabela(self.chamadas), console=console, refresh_per_second=4)

    def __enter__(self):
        self.live.start()
        return self

    def __exit__(self, *exc):
        self.live.stop()

    def registrar(self, row):
        self.chamadas.append(row)
        salvar_csv(row)
        self.live.update(montar_tabela(self.chamadas))