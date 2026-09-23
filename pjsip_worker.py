"""Roda o PJSUA2 num processo do sistema operacional totalmente isolado do
Flask. É necessário porque a extensão nativa `_pjsua2...pyd` deste projeto
(compilada por fora, não é um build oficial do PJSIP) crasha com
"Segmentation fault" quando existe qualquer outra thread Python ativa no
mesmo processo enquanto uma chamada está em andamento — o que acontecia
tanto rodando o teste numa thread separada quanto na própria thread
principal, sempre que o servidor Flask também tinha threads vivas no
processo. Isolando em outro processo, o PJSUA2 fica sozinho, exatamente
como no script `main.py` original rodado via linha de comando.
"""
from queue import Empty

from registro import salvar_csv
from main import criar_endpoint_e_conta, executar_bateria


class _PainelProcesso:
    """Implementa a interface .registrar(row) esperada por TesteCall/
    executar_bateria: grava no mesmo CSV de sempre e também manda o
    resultado pela fila de eventos, para o processo do Flask espelhar."""

    def __init__(self, fila_eventos):
        self._fila_eventos = fila_eventos

    def registrar(self, row):
        salvar_csv(row)
        self._fila_eventos.put({"tipo": "resultado", "row": row})


def _fazer_callback_progresso(fila_eventos):
    def _callback(destino, operadora, etapa):
        fila_eventos.put({
            "tipo": "progresso",
            "destino": destino,
            "operadora": operadora,
            "etapa": etapa,
        })
    return _callback


def processo_pjsip(fila_comandos, fila_eventos, stop_event):
    """Ponto de entrada do processo filho. Fica esperando pedidos de teste
    (dicts de config) na fila_comandos; entre um teste e outro, bombeia os
    eventos do PJSIP para manter registro/keep-alive vivos."""
    painel = _PainelProcesso(fila_eventos)
    on_progresso = _fazer_callback_progresso(fila_eventos)

    ep = None
    acc = None

    while True:
        try:
            config = fila_comandos.get(timeout=0.02)
        except Empty:
            if ep is not None:
                ep.libHandleEvents(10)
            continue

        try:
            if ep is None:
                ep, acc = criar_endpoint_e_conta(config)

            fila_eventos.put({"tipo": "iniciado"})
            executar_bateria(
                ep, acc, config, painel,
                stop_event=stop_event,
                on_progresso=on_progresso,
            )
        except Exception as exc:
            fila_eventos.put({"tipo": "erro", "mensagem": str(exc)})
        finally:
            fila_eventos.put({"tipo": "finalizado"})
