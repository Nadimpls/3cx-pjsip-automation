import csv
import io
import multiprocessing as mp
import os
import threading

from flask import Flask, jsonify, request, render_template, send_from_directory, Response

from config_manager import carregar_config, salvar_config, obter_senha, config_publica, OPERADORAS_DISPONIVEIS
from registro import PainelWeb, CAMPOS_CSV, CENARIOS_VALIDOS, dias_disponiveis, resultados_do_dia, resultados_do_dia_com_audio, audios_do_dia, estatisticas_por_operadora, estatisticas_por_dia, chamadas_por_operadora, chamadas_todas_operadoras, evolucao_todas_operadoras, atualizar_campos_chamada
from pjsip_worker import processo_pjsip

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIOS_DIR = os.path.join(BASE_DIR, "audios")

app = Flask(__name__)

painel_web = PainelWeb()

_lock = threading.Lock()

# O PJSUA2 roda inteiramente num processo do SO separado (pjsip_worker.py),
# nunca no processo do Flask — ver o docstring de pjsip_worker.py para o
# porquê. A comunicação é só por filas/eventos entre processos.
_fila_comandos = mp.Queue()
_fila_eventos = mp.Queue()
_stop_event = mp.Event()
_processo = None

_estado = {
    "rodando": False,
    "operadora_atual": None,
    "numero_atual": None,
    "etapa": None,
    "total_testes_planejados": 0,
    "testes_concluidos": 0,
    "erro": None,
    "cenario": None,
}


def _montar_config_execucao(cenario="ligado"):
    config_disco = carregar_config()
    return {
        "sip_domain": config_disco["sip_domain"],
        "porta_sip": config_disco["porta_sip"],
        "ramal": config_disco["ramal"],
        "auth_id": config_disco["auth_id"],
        "senha": obter_senha(config_disco),
        "operadoras": config_disco["operadoras_habilitadas"],
        "destinos": config_disco["destinos"],
        "cenario": cenario,
    }


def _drenar_eventos():
    """Roda numa thread do processo do Flask, só lendo a fila de eventos
    vinda do processo do PJSUA2 e atualizando o estado/resultados em
    memória — nunca toca em pjsua2 diretamente."""
    while True:
        evento = _fila_eventos.get()
        tipo = evento.get("tipo")

        if tipo == "resultado":
            painel_web.adicionar_resultado(evento["row"])
        elif tipo == "progresso":
            with _lock:
                _estado["numero_atual"] = evento["destino"]
                _estado["operadora_atual"] = evento["operadora"]
                _estado["etapa"] = evento["etapa"]
                if evento["etapa"] == "concluido":
                    _estado["testes_concluidos"] += 1
        elif tipo == "iniciado":
            with _lock:
                _estado["rodando"] = True
        elif tipo == "erro":
            with _lock:
                _estado["erro"] = evento["mensagem"]
        elif tipo == "finalizado":
            with _lock:
                _estado["rodando"] = False
                _estado["operadora_atual"] = None
                _estado["numero_atual"] = None
                _estado["etapa"] = None


def _iniciar_processo_pjsip():
    processo = mp.Process(
        target=processo_pjsip,
        args=(_fila_comandos, _fila_eventos, _stop_event),
        daemon=True,
    )
    processo.start()
    return processo


def _vigiar_processo():
    """O processo do PJSUA2 nunca deveria terminar sozinho (seu loop é
    infinito) — se ele sumir foi crash nativo (Segmentation fault), que não
    dá pra capturar em Python. Aqui a gente detecta isso, avisa a interface
    em vez de deixar tudo travado em "Rodando" pra sempre, e sobe um
    processo novo pra dar pra tentar de novo sem reiniciar o app.py."""
    global _processo
    while True:
        _processo.join(timeout=1)
        if _processo.is_alive():
            continue

        with _lock:
            estava_rodando = _estado["rodando"]
            _estado["rodando"] = False
            _estado["operadora_atual"] = None
            _estado["numero_atual"] = None
            _estado["etapa"] = None
            if estava_rodando:
                _estado["erro"] = (
                    "O processo do PJSUA2 encerrou inesperadamente (crash nativo) "
                    "durante o teste. Um novo processo foi iniciado — pode tentar de novo."
                )

        _processo = _iniciar_processo_pjsip()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(config_publica())


@app.route("/api/config", methods=["POST"])
def api_post_config():
    dados = request.get_json(force=True) or {}
    config_atualizada = salvar_config(dados)
    return jsonify(config_publica(config_atualizada))


@app.route("/api/operadoras", methods=["GET"])
def api_operadoras():
    return jsonify(OPERADORAS_DISPONIVEIS)


@app.route("/api/test/start", methods=["POST"])
def api_start():
    with _lock:
        if _estado["rodando"]:
            return jsonify({"erro": "Já existe um teste em andamento."}), 409

    dados = request.get_json(silent=True) or {}
    cenario = dados.get("cenario", "ligado")
    if cenario not in CENARIOS_VALIDOS:
        return jsonify({"erro": "Cenário inválido — use 'ligado' ou 'desligado'."}), 400

    config = _montar_config_execucao(cenario=cenario)

    if not config["destinos"]:
        return jsonify({"erro": "Adicione ao menos um número de destino."}), 400
    if not config["operadoras"]:
        return jsonify({"erro": "Selecione ao menos uma operadora."}), 400
    if not config["senha"]:
        return jsonify({"erro": "Configure a senha SIP antes de iniciar."}), 400

    _stop_event.clear()
    with _lock:
        _estado.update({
            "rodando": True,
            "operadora_atual": None,
            "numero_atual": None,
            "etapa": None,
            "total_testes_planejados": len(config["destinos"]) * len(config["operadoras"]),
            "testes_concluidos": 0,
            "erro": None,
            "cenario": cenario,
        })

    _fila_comandos.put(config)

    return jsonify({"ok": True})


@app.route("/api/test/stop", methods=["POST"])
def api_stop():
    _stop_event.set()
    return jsonify({"ok": True})


@app.route("/api/test/status", methods=["GET"])
def api_status():
    with _lock:
        return jsonify(dict(_estado))


@app.route("/api/results", methods=["GET"])
def api_results():
    return jsonify(painel_web.obter_resultados())


@app.route("/api/historico/dias", methods=["GET"])
def api_historico_dias():
    return jsonify(dias_disponiveis())


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    data = request.args.get("data") or None
    cenario = request.args.get("cenario") or None
    return jsonify(estatisticas_por_operadora(data=data, cenario=cenario))


@app.route("/api/dashboard/evolucao", methods=["GET"])
def api_dashboard_evolucao():
    operadora = request.args.get("operadora")
    cenario = request.args.get("cenario") or None
    if not operadora:
        return jsonify({"erro": "Parâmetro 'operadora' é obrigatório."}), 400
    return jsonify(estatisticas_por_dia(operadora, cenario=cenario))


@app.route("/api/dashboard/chamadas", methods=["GET"])
def api_dashboard_chamadas():
    operadora = request.args.get("operadora")
    cenario = request.args.get("cenario") or None
    if not operadora:
        return jsonify({"erro": "Parâmetro 'operadora' é obrigatório."}), 400
    return jsonify(chamadas_por_operadora(operadora, cenario=cenario))


@app.route("/api/dashboard/evolucao-todas", methods=["GET"])
def api_dashboard_evolucao_todas():
    cenario = request.args.get("cenario") or None
    return jsonify(evolucao_todas_operadoras(cenario=cenario))


@app.route("/api/dashboard/chamadas-todas", methods=["GET"])
def api_dashboard_chamadas_todas():
    cenario = request.args.get("cenario") or None
    return jsonify(chamadas_todas_operadoras(cenario=cenario))


@app.route("/api/historico/<data>", methods=["GET"])
def api_historico_dia(data):
    return jsonify(resultados_do_dia_com_audio(data, AUDIOS_DIR))


@app.route("/api/historico/atualizar", methods=["POST"])
def api_historico_atualizar():
    """Grava anotações manuais (BINA real informada / SPAM) numa chamada já
    registrada — dados que o sistema não tem como capturar sozinho."""
    dados = request.get_json(force=True) or {}
    timestamp = dados.get("timestamp")
    tronco = dados.get("tronco")
    numero = dados.get("numero")

    if not timestamp or not tronco or not numero:
        return jsonify({"erro": "timestamp, tronco e numero são obrigatórios."}), 400

    campos = {}
    if "bina_manual" in dados:
        campos["bina_manual"] = dados["bina_manual"]
    if "spam" in dados:
        campos["spam"] = dados["spam"]

    if not campos:
        return jsonify({"erro": "Nada para atualizar."}), 400

    sucesso = atualizar_campos_chamada(timestamp, tronco, numero, campos)
    if not sucesso:
        return jsonify({"erro": "Chamada não encontrada no histórico."}), 404

    return jsonify({"ok": True})


@app.route("/api/historico/<data>/csv", methods=["GET"])
def api_historico_dia_csv(data):
    linhas = resultados_do_dia(data)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CAMPOS_CSV)
    writer.writeheader()
    writer.writerows(linhas)

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=testes_{data}.csv"},
    )


@app.route("/api/audios", methods=["GET"])
def api_audios():
    if not os.path.isdir(AUDIOS_DIR):
        return jsonify([])
    arquivos = sorted(
        (f for f in os.listdir(AUDIOS_DIR) if f.lower().endswith(".wav")),
        reverse=True,
    )
    return jsonify(arquivos)


@app.route("/api/audios/dia/<data>", methods=["GET"])
def api_audios_dia(data):
    return jsonify(audios_do_dia(data, AUDIOS_DIR))


@app.route("/api/audios/<nome_arquivo>", methods=["GET"])
def api_audio_arquivo(nome_arquivo):
    return send_from_directory(AUDIOS_DIR, nome_arquivo)


if __name__ == "__main__":
    _processo = _iniciar_processo_pjsip()

    threading.Thread(target=_drenar_eventos, daemon=True).start()
    threading.Thread(target=_vigiar_processo, daemon=True).start()

    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
