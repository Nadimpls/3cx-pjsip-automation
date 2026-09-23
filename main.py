import csv
import json
import os
import re
import time
import pjsua2 as pj
from gravador import iniciar_gravacao, parar_gravacao, reconectar_gravacao
from rich.console import Console
from registro import PainelAoVivo, extrair_header_sip, extrair_q850_cause, gerar_batch_id
from config_manager import carregar_config, obter_senha

Console = Console()

TECH = "170"  # tech padrão, usado pelas operadoras que não têm tech própria em TECH_OPERADORAS

TRONCO_OPERADORAS = {
    "OTIMA": "2223",
    "PRIMACOM": "2224",
    "OKTOR": "2225",
    "AGIL": "2226",
    "EMBRATEL": "2221",
    "LEMIT": "1234",
}

TECH_OPERADORAS = {
    "LEMIT": "225",
}

CODIGO_ROTA = "5060"

def numero_discagem(operadora, numero_ddd):
    tronco = TRONCO_OPERADORAS.get(operadora)
    if tronco is None:
        raise ValueError(f"OPERADORA '{operadora}' não identificada em TRONCO_OPERADORAS")
    tech = TECH_OPERADORAS.get(operadora, TECH)
    return f"{tech}{tronco}{numero_ddd}"


class TesteCall(pj.Call):

    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, operadora=None, telefone=None, ip=None, ramal=None, painel=None, batch_id=None, cenario="ligado"):
        pj.Call.__init__(self, acc, call_id)
        self.t_invite = None
        self.t_ring = None
        self.t_answer = None
        self.t_end = None
        self.last_status_code = None
        self.last_status_text = None
        self.operadora = operadora
        self.telefone = telefone
        self.ip = ip
        self.ramal = ramal
        self.painel = painel   # <--- Recebe o painel aqui
        self.batch_id = batch_id
        self.cenario = cenario  # "ligado" ou "desligado" — escolhido ao iniciar a bateria
        self.desligamos_local = False  # True se fomos nós que pedimos hangup (ex.: stop_event)

        # Dados da Fase 2, coletados aos poucos conforme a chamada progride
        self.eventos_sip = []       # [{"codigo", "motivo", "t_desde_invite_s"}, ...]
        self._ultimo_codigo_evento = None
        self.bina_configurado = ramal
        self.bina_enviado = None
        self.bina_header_from = None
        self.bina_header_pai = None
        self.bina_header_rpid = None
        self.q850_cause = None
        self.sip_mensagem_bruta = None  # texto cru da última mensagem SIP recebida (sem parsing/interpretação)

        # Dados de RTP/codec da Fase 3, amostrados periodicamente enquanto a
        # chamada está confirmada (só existem depois que a mídia sobe). O
        # PJSIP já mantém jitter/RTT como estatística agregada (média/máximo
        # desde o início da mídia, via MathStat) — a cada amostra a gente só
        # guarda a leitura mais recente, que já reflete a chamada inteira
        # até aquele ponto; não precisamos recalcular médias por fora.
        self.codec = None
        self.payload_type = None
        self._rtt_medio_usec = None
        self._packets_enviados = None
        self._packets_recebidos = None
        self._packet_loss = None
        self._jitter_medio_usec = None
        self._jitter_maximo_usec = None

    def amostrar_rtp(self):
        """Tira um snapshot do codec e dos contadores RTP/RTCP da chamada
        (Call.getStreamInfo/getStreamStat — dados que o próprio PJSUA2 já
        expõe, nada calculado por fora). Chamado periodicamente pelo loop
        de espera em executar_bateria enquanto a chamada está ativa; sem
        media (chamada não atendida) isso simplesmente não faz nada, sem
        erro."""
        try:
            info = self.getStreamInfo(0)
            if info and info.codecName:
                self.codec = info.codecName
                self.payload_type = info.txPt

            stat = self.getStreamStat(0)
            if stat and stat.rtcp:
                rtcp = stat.rtcp
                # jitterUsec/rttUsec são pj::MathStat (n/min/max/last/mean),
                # o PJSIP já agrega isso sozinho — não são números soltos.
                if rtcp.rttUsec:
                    self._rtt_medio_usec = rtcp.rttUsec.mean
                self._packets_enviados = rtcp.txStat.pkt
                self._packets_recebidos = rtcp.rxStat.pkt
                self._packet_loss = rtcp.rxStat.loss
                if rtcp.rxStat.jitterUsec:
                    self._jitter_medio_usec = rtcp.rxStat.jitterUsec.mean
                    self._jitter_maximo_usec = rtcp.rxStat.jitterUsec.max
        except Exception:
            pass

    def onCallState(self, prm):
        ci = self.getInfo()
        now = time.time()

        if ci.state == pj.PJSIP_INV_STATE_CALLING:
            self.t_invite = now
        elif ci.state == pj.PJSIP_INV_STATE_EARLY:
            if self.t_ring is None:
                self.t_ring = now
                self.last_status_code = ci.lastStatusCode
                self.last_status_text = ci.lastReason
        elif ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            self.t_answer = now
            nome_arquivo = f"{self.operadora}_{self.telefone}_{time.strftime('%Y%m%d_%H%M%S')}.wav"
            iniciar_gravacao(self, file_path=nome_arquivo)
            
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            self.t_end = now
            self.last_status_code = ci.lastStatusCode
            self.last_status_text = ci.lastReason
            
            parar_gravacao(self)
            self.registrar_resultado()

    def onCallMediaState(self, prm):
        # O PJSIP recria a sessão de mídia quando renegocia a chamada (ex.:
        # o re-INVITE automático logo após atender, pra fechar em um único
        # codec) — isso desconectava a gravação silenciosamente a partir
        # desse momento. Reconecta sempre que a mídia mudar; não faz nada
        # se a gravação ainda não tiver começado.
        reconectar_gravacao(self)

    def onCallTsxState(self, prm):
        # Dispara a cada transição de transação SIP (cada resposta
        # provisória/final). Usamos só pra: (1) registrar cada código SIP
        # distinto com timestamp, coisa que onCallState não dá (ele só pega
        # o primeiro EARLY); e (2) tentar ler o texto SIP cru que o próprio
        # PJSUA2 já entrega (wholeMsg) pra extrair BINA/Q.850 quando
        # existirem. Nunca deixamos uma falha aqui atrapalhar a chamada.
        try:
            ci = self.getInfo()
            codigo = ci.lastStatusCode
            motivo = ci.lastReason

            if codigo and codigo != self._ultimo_codigo_evento:
                t_relativo = round(time.time() - self.t_invite, 2) if self.t_invite else None
                self.eventos_sip.append({
                    "codigo": codigo,
                    "motivo": motivo,
                    "t_desde_invite_s": t_relativo,
                })
                self._ultimo_codigo_evento = codigo

            src = prm.e.body.tsxState.src
            texto = None
            if src.rdata is not None and src.rdata.wholeMsg:
                texto = src.rdata.wholeMsg
                # Guarda o texto cru da última mensagem RECEBIDA da rede
                # (não a que nós mandamos) — é literalmente o que a
                # operadora respondeu, sem nenhum parsing por cima.
                self.sip_mensagem_bruta = texto
            elif src.tdata is not None and src.tdata.wholeMsg:
                texto = src.tdata.wholeMsg

            if texto:
                if self.bina_header_from is None:
                    from_header = extrair_header_sip(texto, "From")
                    if from_header:
                        self.bina_header_from = from_header
                        m = re.search(r"sip:([^@;>]+)@", from_header, re.IGNORECASE)
                        if m:
                            self.bina_enviado = m.group(1)

                pai = extrair_header_sip(texto, "P-Asserted-Identity")
                if pai:
                    self.bina_header_pai = pai

                rpid = extrair_header_sip(texto, "Remote-Party-ID")
                if rpid:
                    self.bina_header_rpid = rpid

                if self.q850_cause is None:
                    causa = extrair_q850_cause(texto)
                    if causa:
                        self.q850_cause = causa
        except Exception:
            pass

    def registrar_resultado(self):
        pdd_s = None
        if self.t_invite and self.t_ring:
            pdd_s = round(self.t_ring - self.t_invite, 2)  # Segundos com 2 casas decimais

        setup_s = None
        if self.t_invite and self.t_answer:
            setup_s = round(self.t_answer - self.t_invite, 2)

        # Durações adicionais (Fase 2) — mesma fonte de tempo (time.time())
        # já usada pra PDD/setup, só medindo outros trechos da chamada.
        ring_duration_s = None
        if self.t_ring and self.t_answer:
            ring_duration_s = round(self.t_answer - self.t_ring, 2)

        talk_duration_s = None
        if self.t_answer and self.t_end:
            talk_duration_s = round(self.t_end - self.t_answer, 2)

        total_duration_s = None
        if self.t_invite and self.t_end:
            total_duration_s = round(self.t_end - self.t_invite, 2)

        # release_by é uma INFERÊNCIA por convenção (o PJSUA2 não entrega um
        # "quem desligou" pronto) — por isso release_by_fonte fica marcado
        # explicitamente, pra nunca ser lido como um fato garantido.
        if self.desligamos_local:
            release_by = "LOCAL"
        elif self.t_answer is not None:
            release_by = "REMOTE"
        else:
            release_by = "NETWORK"

        # RTP/codec (Fase 3) — só existem se a chamada chegou a ter mídia
        # (atendida). jitter/RTT já vêm agregados (média/máximo) direto do
        # PJSIP na última amostra antes do desligamento; packets/loss idem.
        # Nada aqui é inventado: se não amostrou nenhuma vez (não atendida,
        # ou mídia muito curta), fica None/N-D.
        jitter_medio_ms = round(self._jitter_medio_usec / 1000, 2) if self._jitter_medio_usec is not None else None
        jitter_maximo_ms = round(self._jitter_maximo_usec / 1000, 2) if self._jitter_maximo_usec is not None else None
        rtt_ms = round(self._rtt_medio_usec / 1000, 2) if self._rtt_medio_usec is not None else None

        packet_loss_pct = None
        if self._packet_loss is not None and self._packets_recebidos is not None:
            total_esperado = self._packet_loss + self._packets_recebidos
            if total_esperado > 0:
                packet_loss_pct = round(self._packet_loss / total_esperado * 100, 2)

        row = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ramal": self.ramal,
            "tronco": self.operadora,
            "pdd_s": pdd_s,
            "setup_time_s": setup_s,
            "sip_code": self.last_status_code,
            "sip_reason": self.last_status_text,
            "atendida": self.t_answer is not None,
            "Número": self.telefone,
            "batch_id": self.batch_id,
            "bina_configurado": self.bina_configurado,
            "bina_enviado": self.bina_enviado,
            "bina_header_from": self.bina_header_from,
            "bina_header_pai": self.bina_header_pai,
            "bina_header_rpid": self.bina_header_rpid,
            "sip_events": json.dumps(self.eventos_sip, ensure_ascii=False),
            "q850_cause": self.q850_cause,
            "release_by": release_by,
            "release_by_fonte": "inferido",
            "ring_duration_s": ring_duration_s,
            "talk_duration_s": talk_duration_s,
            "total_duration_s": total_duration_s,
            "codec": self.codec,
            "payload_type": self.payload_type,
            "packets_enviados": self._packets_enviados,
            "packets_recebidos": self._packets_recebidos,
            "packet_loss": self._packet_loss,
            "packet_loss_pct": packet_loss_pct,
            "jitter_medio_ms": jitter_medio_ms,
            "jitter_maximo_ms": jitter_maximo_ms,
            "rtt_ms": rtt_ms,
            "cenario": self.cenario,
            "sip_mensagem_bruta": self.sip_mensagem_bruta,
        }

        # Envia os dados para o painel atualizar a tabela e salvar no CSV automaticamente
        if self.painel:
            self.painel.registrar(row)


def criar_endpoint_e_conta(config, nome_thread="main_thread"):
    """Sobe o Endpoint PJSUA2, o transporte UDP e registra a conta SIP.

    `config` é um dict simples: sip_domain, porta_sip, ramal, auth_id, senha
    (texto puro), operadoras, destinos. Quem chama (CLI ou app web) resolve
    a senha antes de passar pra cá — esta função não sabe de onde ela veio.
    """
    ep = pj.Endpoint()
    ep.libCreate()

    ep_cfg = pj.EpConfig()
    log_cfg = ep_cfg.logConfig
    log_cfg.level = 4
    log_cfg.consoleLevel = 4
    # Esta extensão PJSUA2 (binário compilado por fora) crasha com
    # "Segmentation fault" quando a thread interna que o próprio PJSIP cria
    # ("pjsua_0") tenta chamar de volta pro Python (ex.: onCallState) sem
    # ter inicializado o estado do interpretador corretamente — um bug do
    # binding, confirmado via backtrace do gdb. Desativando as threads
    # internas do PJSUA2 e mantendo mainThreadOnly ligado, todo o
    # processamento (e os callbacks pro Python) passa a acontecer só na
    # thread que chama ep.libHandleEvents(), evitando esse crash.
    ep_cfg.uaConfig.threadCnt = 0
    ep_cfg.uaConfig.mainThreadOnly = True
    ep.libInit(ep_cfg)

    sip_tp_cfg = pj.TransportConfig()
    sip_tp_cfg.port = config["porta_sip"]
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, sip_tp_cfg)

    ep.libStart()

    ep.libRegisterThread(nome_thread)

    acc_cfg = pj.AccountConfig()
    acc_cfg.idUri = f"sip:{config['ramal']}@{config['sip_domain']}"
    acc_cfg.regConfig.registrarUri = f"sip:{config['sip_domain']}"

    cred = pj.AuthCredInfo("digest", "*", config["auth_id"], 0, config["senha"])
    acc_cfg.sipConfig.authCreds.append(cred)

    acc = pj.Account()
    acc.create(acc_cfg)

    time.sleep(2)

    return ep, acc


def executar_bateria(ep, acc, config, painel, stop_event=None, on_progresso=None):
    """Roda a bateria de testes (todos os destinos x todas as operadoras).

    Lógica idêntica à do script original — só passou a ler `config` em vez
    de constantes fixas, a checar `stop_event` entre um teste e outro para
    permitir parar pela interface web sem derrubar o processo, e a chamar
    `on_progresso(destino, operadora, etapa)` (etapa: "iniciando"/"concluido")
    para a interface web saber qual teste está rodando agora.
    """
    ramal = config["ramal"]
    sip_domain = config["sip_domain"]
    cenario = config.get("cenario", "ligado")
    batch_id = gerar_batch_id()
    Console.print(f"[bold cyan]Batch: {batch_id} — cenário: {cenario}")

    # LOOP 1: Percorre cada número da lista de destinos
    for destino in config["destinos"]:
        if stop_event is not None and stop_event.is_set():
            break

        Console.print(f"\n[bold red] ========================================")
        Console.print(f"[bold red] INICIANDO TESTES PARA O NÚMERO: {destino}")
        Console.print(f"[bold red] ========================================")

        # LOOP 2: Para cada número, testa todas as operadoras em sequência
        for operadora in config["operadoras"]:
            if stop_event is not None and stop_event.is_set():
                break

            Console.print(f"\n[bold cyan]--- Testando operadora: {operadora} para o número {destino} ---")

            if on_progresso is not None:
                on_progresso(destino, operadora, "iniciando")

            numero_fical = numero_discagem(operadora, destino)

            call = TesteCall(
                acc=acc,
                call_id=pj.PJSUA_INVALID_ID,
                operadora=operadora,
                telefone=destino,
                ip=sip_domain,
                ramal=ramal,
                painel=painel,  # <--- Passando o painel para a chamada
                batch_id=batch_id,
                cenario=cenario
            )

            call_prm = pj.CallOpParam(True)
            dst_uri = f"sip:{numero_fical}@{sip_domain}"

            # 2. CAPTURAR ERROS NATIVOS DO C++
            try:
                call.makeCall(dst_uri, call_prm)
            except pj.Error as e:
                Console.print(f"[bold red]Erro ao disparar makeCall para {dst_uri}: {e.info()}")
                continue

            # 3. BOMBEAR EVENTOS DO PJSIP NO LOOP DE ESPERA
            proxima_amostra_rtp = 0.0
            while True:
                try:
                    ep.libHandleEvents(50)  # Mantém a pilha SIP ativa e escutando a rede
                    state = call.getInfo().state
                    if state >= pj.PJSIP_INV_STATE_DISCONNECTED:
                        break

                    # Amostra RTP/codec ~1x por segundo enquanto atendida
                    # (Fase 3) — jitter precisa de várias amostras pra dar
                    # médio/máximo; packets/loss/rtt ficam com a mais recente.
                    if state == pj.PJSIP_INV_STATE_CONFIRMED:
                        agora = time.time()
                        if agora >= proxima_amostra_rtp:
                            call.amostrar_rtp()
                            proxima_amostra_rtp = agora + 1.0
                    if stop_event is not None and stop_event.is_set():
                        Console.print("[bold yellow]Parada solicitada — desligando a chamada em andamento...")
                        call.desligamos_local = True
                        try:
                            call.hangup(pj.CallOpParam())
                        except pj.Error:
                            pass
                        break
                except Exception as err:
                    Console.print(f"[bold yellow]Exceção no monitoramento da chamada: {err}")
                    break

            Console.print(f"[bold red]Teste com {operadora} finalizado. Pausando 2 segundos...")

            if on_progresso is not None:
                on_progresso(destino, operadora, "concluido")

            time.sleep(2)

        Console.print(f"\n[bold red][CONCLUÍDO] Todos os testes para o número {destino} foram finalizados.")
        time.sleep(3)

    Console.print("\n[bold red]Fila geral de chamadas concluída. Todos os dados foram salvos no CSV e áudios na pasta.")


def main():
    config_disco = carregar_config()
    config = {
        "sip_domain": config_disco["sip_domain"],
        "porta_sip": config_disco["porta_sip"],
        "ramal": config_disco["ramal"],
        "auth_id": config_disco["auth_id"],
        "senha": obter_senha(config_disco),
        "operadoras": config_disco["operadoras_habilitadas"],
        "destinos": config_disco["destinos"],
    }

    ep, acc = criar_endpoint_e_conta(config)

    # ATIVA O PAINEL AO VIVO DO RICH ENQUANTO RODE AS CHAMADAS
    with PainelAoVivo() as painel:
        executar_bateria(ep, acc, config, painel)


if __name__ == "__main__":
    main()