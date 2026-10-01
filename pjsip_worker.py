import traceback
from queue import Empty

from registro import salvar_csv
from main import criar_endpoint_e_conta, executar_bateria


class _PainelProcesso:

    def __init__(self, fila_eventos):
        self._fila_eventos = fila_eventos

    def registrar(self, row):
        # Garante a conversão de sqlite3.Row / tuple para dict se necessário
        if isinstance(row, tuple) and not isinstance(row, dict):
            row = dict(row)
            
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
    """Ponto de entrada do processo filho."""
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
            # Garante que 'config' seja um dicionário
            if isinstance(config, tuple) and not isinstance(config, dict):
                config = dict(config)

            if ep is None:
                ep, acc = criar_endpoint_e_conta(config)

            fila_eventos.put({"tipo": "iniciado"})
            executar_bateria(
                ep, acc, config, painel,
                stop_event=stop_event,
                on_progresso=on_progresso,
            )
        except Exception as exc:
            # Exibe o traceback detalhado no console para rastrear o erro
            print("\n" + "=" * 60)
            print("[ERRO FATAL NO WORKER PJSIP]:")
            traceback.print_exc()
            print("=" * 60 + "\n")

            fila_eventos.put({"tipo": "erro", "mensagem": str(exc)})
        finally:
            fila_eventos.put({"tipo": "finalizado"})