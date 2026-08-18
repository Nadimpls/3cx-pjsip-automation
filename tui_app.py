# -*- coding: utf-8 -*-
"""
Interface Textual para a automação de testes SIP.

Rodar com: python run_tui.py (dentro do terminal MSYS2 MinGW64)

Fluxo:
  1. Tela de setup: escolhe modo de teste, destinos e operadoras.
  2. Ao clicar "Iniciar teste", a automação (executar_automacao, de main.py)
     roda numa thread separada — o loop de eventos do pjsua2 precisa rodar
     continuamente e não pode travar o event loop do Textual.
  3. Cada atualização de chamada chega na UI via app.call_from_thread,
     através do PainelTUI (tui_painel.py), que é passado como painel_factory.
"""
from __future__ import annotations

import threading
from datetime import datetime

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    RichLog,
    Select,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

import config as c

CODIGOS_RUIM = {403, 404, 486, 480, 502, 503, 504}


class StatsBar(Static):
    total = reactive(0)
    sucesso = reactive(0)
    falha = reactive(0)

    def watch_total(self, value) -> None:
        self.refresh()

    def watch_sucesso(self, value) -> None:
        self.refresh()

    def watch_falha(self, value) -> None:
        self.refresh()

    def render(self) -> str:
        taxa = f"{(self.sucesso / self.total * 100):.1f}%" if self.total else "—"
        return (
            f" Total: {self.total}   "
            f"[green]OK: {self.sucesso}[/green]   "
            f"[red]Falha: {self.falha}[/red]   "
            f"Taxa de sucesso: {taxa} "
        )


class SipTesterApp(App):
    CSS = """
    #setup { padding: 1 2; height: auto; border: round $accent; }
    #setup.hidden { display: none; }
    #live { display: none; }
    #live.visible { display: block; height: 1fr; }
    SelectionList { height: 8; border: round $accent; margin-bottom: 1; }
    DataTable { height: 1fr; }
    RichLog { height: 12; border: round $accent; }
    StatsBar { height: 1; padding: 0 1; background: $panel; }
    #botoes, #botoes_live { height: 3; align: center middle; }
    """

    BINDINGS = [
        ("q", "quit", "Sair"),
        ("s", "toggle_start_stop", "Iniciar/Parar"),
    ]

    def __init__(self):
        super().__init__()
        self.app_state = {"running": False}
        self.worker_thread: threading.Thread | None = None
        self.modo = "padrao"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="setup"):
            yield Static("[b]Configuração do teste[/b]\n")
            yield Static("Modo de teste:")
            yield Select(
                [
                    ("Padrão (1 chamada por par)", "padrao"),
                    ("Rate sensitivity (frequência de chamada)", "rate_sensitivity"),
                    ("Reattach (baseline / modo avião / sondagem)", "reattach"),
                ],
                value="padrao",
                id="modo_select",
            )
            yield Static("Destinos:")
            yield SelectionList[str](
                *[Selection(d, d, True) for d in c.LISTA_DESTINOS],
                id="destinos_list",
            )
            yield Static("Operadoras:")
            yield SelectionList[str](
                *[Selection(o, o, True) for o in c.OPERADORAS_TESTE],
                id="operadoras_list",
            )
            with Horizontal(id="botoes"):
                yield Button("Iniciar teste", id="btn_start", variant="success")

        with Vertical(id="live"):
            yield StatsBar(id="stats")
            yield DataTable(id="tabela_resultados")
            yield RichLog(id="log", highlight=True, markup=True, wrap=True)
            with Horizontal(id="botoes_live"):
                yield Button("Parar teste", id="btn_stop", variant="error")

        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#tabela_resultados", DataTable)
        table.add_columns(
            "Horário",
            "Operadora",
            "Destino",
            "SIP",
            "Motivo",
            "PDD (s)",
            "Duração",
            "Classificação",
        )
        table.cursor_type = "row"
        table.zebra_stripes = True

    # ---------------- controles ----------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_start":
            self.iniciar_teste()
        elif event.button.id == "btn_stop":
            self.parar_teste()

    def action_toggle_start_stop(self) -> None:
        if self.app_state["running"]:
            self.parar_teste()
        else:
            self.iniciar_teste()

    def iniciar_teste(self) -> None:
        if self.app_state["running"]:
            return

        modo_select = self.query_one("#modo_select", Select)
        destinos_sel = list(self.query_one("#destinos_list", SelectionList).selected)
        operadoras_sel = list(
            self.query_one("#operadoras_list", SelectionList).selected
        )

        log = self.query_one("#log", RichLog)

        if not destinos_sel or not operadoras_sel:
            log.write(
                "[bold red]Selecione ao menos um destino e uma operadora antes de"
                " iniciar.[/bold red]"
            )
            return

        self.modo = modo_select.value
        c.LISTA_DESTINOS = destinos_sel
        c.OPERADORAS_TESTE = operadoras_sel

        self.query_one("#setup").add_class("hidden")
        self.query_one("#live").add_class("visible")

        self.app_state["running"] = True
        log.write(
            f"[bold cyan]Iniciando modo '{self.modo}' — {len(destinos_sel)} "
            f"destino(s) x {len(operadoras_sel)} operadora(s)[/bold cyan]"
        )

        # import tardio: evita puxar pjsua2 antes do usuário decidir iniciar
        from main import executar_automacao
        from tui_painel import PainelTUI

        def _run():
            try:
                executar_automacao(
                    modo=self.modo,
                    log_callback=self.log_thread_safe,
                    app_state=self.app_state,
                    painel_factory=lambda: PainelTUI(self),
                )
            except Exception as err:
                self.call_from_thread(
                    log.write, f"[bold red]Erro fatal na automação: {err}[/bold red]"
                )
            finally:
                self.app_state["running"] = False
                self.call_from_thread(self._on_finished)

        self.worker_thread = threading.Thread(target=_run, daemon=True)
        self.worker_thread.start()

    def parar_teste(self) -> None:
        if not self.app_state["running"]:
            return
        self.app_state["running"] = False
        self.query_one("#log", RichLog).write(
            "[yellow]Parando após o ciclo atual em andamento...[/yellow]"
        )

    def _on_finished(self) -> None:
        self.query_one("#log", RichLog).write(
            "[bold green]Teste finalizado.[/bold green]"
        )

    # -------- callbacks chamados pela thread de automação (via call_from_thread) --------

    def log_thread_safe(self, texto: str) -> None:
        self.query_one("#log", RichLog).write(texto)

    def adicionar_resultado(self, row_data: dict) -> None:
        table = self.query_one("#tabela_resultados", DataTable)
        stats = self.query_one("#stats", StatsBar)

        sip_code_raw = row_data.get("sip_code") or row_data.get("SIP_CODE") or ""
        try:
            sip_code_int = int(str(sip_code_raw).split()[0])
        except (ValueError, IndexError):
            sip_code_int = None

        if sip_code_int in CODIGOS_RUIM:
            sip_cell = Text(str(sip_code_raw), style="bold red")
        elif sip_code_int == 200:
            sip_cell = Text(str(sip_code_raw), style="bold green")
        else:
            sip_cell = Text(str(sip_code_raw), style="yellow")

        table.add_row(
            datetime.now().strftime("%H:%M:%S"),
            str(row_data.get("tronco") or row_data.get("Operadora") or ""),
            str(row_data.get("Número") or row_data.get("numero") or ""),
            sip_cell,
            str(row_data.get("sip_reason") or row_data.get("SIP_REASON") or ""),
            str(row_data.get("pdd_s") or row_data.get("PDD (s)") or ""),
            str(row_data.get("audio_duration_s") or ""),
            str(row_data.get("classificacao") or row_data.get("Atendida") or ""),
        )
        table.scroll_end(animate=False)

        stats.total += 1
        if sip_code_int in CODIGOS_RUIM:
            stats.falha += 1
        else:
            stats.sucesso += 1


if __name__ == "__main__":
    SipTesterApp().run()