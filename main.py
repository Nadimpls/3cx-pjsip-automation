import csv
import json
import os
import re
import time
from db import salvar_registro_chamada
import pjsua2 as pj
from gravador import iniciar_gravacao, parar_gravacao, reconectar_gravacao
from rich.console import Console
from registro import PainelAoVivo, extrair_header_sip, extrair_q850_cause, gerar_batch_id
from config_manager import carregar_config, obter_senha, TECH_PADRAO
from db import init_db, salvar_registro_chamada

Console = Console()

TRONCO_OPERADORAS = {
    "OTIMA": "2223",
    "PRIMACOM": "2224",
    "OKTOR": "2225",
    "AGIL": "2226",
    "EMBRATEL": "2221",
    "LEMIT": "1234",
}

CODIGO_ROTA = "5060"

def numero_discagem(operadora, numero_ddd, tech_por_operadora=None):
    tronco = TRONCO_OPERADORAS.get(operadora)
    if tronco is None:
        raise ValueError(f"OPERADORA '{operadora}' não identificada em TRONCO_OPERADORAS")
    tech = (tech_por_operadora or {}).get(operadora, TECH_PADRAO)
    return f"{tech}{tronco}{numero_ddd}"


class TesteCall(pj.Call):

    def __init__(
        self,
        acc,
        call_id=pj.PJSUA_INVALID_ID,
        operadora=None,
        telefone=None,
        ip=None,
        ramal=None,
        painel=None,
        batch_id=None,
        cenario="ligado",
        rota=None,
    ):
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
        self.painel = painel
        self.batch_id = batch_id
        self.cenario = cenario
        self.rota = rota
        self.desligamos_local = False
        self.eventos_sip = []
        self._ultimo_codigo_evento = None
        self.bina_configurado = ramal
        self.bina_enviado = None
        self.bina_header_from = None
        self.bina_header_pai = None
        self.bina_header_rpid = None
        self.q850_cause = None
        self.sip_mensagem_bruta = None
        self.codec = None
        self.payload_type = None
        self._rtt_medio_usec = None
        self._packets_enviados = None
        self._packets_recebidos = None
        self._packet_loss = None
        self._jitter_medio_usec = None
        self._jitter_maximo_usec = None
        self.recorder = None
        self.nome_arquivo_audio = None

    def amostrar_rtp(self):
        try:
            info = self.getStreamInfo(0)
            if info and info.codecName:
                self.codec = info.codecName
                self.payload_type = info.txPt

            stat = self.getStreamStat(0)
            if stat and stat.rtcp:
                rtcp = stat.rtcp
                if rtcp.rttUsec:
                    self._rtt_medio_usec = rtcp.rttUsec.mean
                self._packets_enviados = rtcp.txStat.pkt
                self._packets_recebidos = rtcp.rxStat.pkt
                self._packet_loss = rtcp.rxStat.loss
                if rtcp.rxStat.jitterUsec:
                    self._jitter_medio_usec = rtcp.rxStat.jitterUsec.mean
                    self._jitter_maximo_usec = (
                        rtcp.rxStat.jitterUsec.max
                    )
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

            # CORREÇÃO 2: Grava o nome do arquivo no atributo da instância (self)
            op_str = self.operadora or "OP"
            tel_str = self.telefone or "TEL"
            self.nome_arquivo_audio = f"{op_str}_{tel_str}_{time.strftime('%Y%m%d_%H%M%S')}.wav"

            try:
                iniciar_gravacao(self, file_path=self.nome_arquivo_audio)
            except Exception as e:
                if self.painel and hasattr(self.painel, "log_erro"):
                    self.painel.log_erro(f"Erro ao iniciar gravação: {e}")

        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            self.t_end = now
            self.last_status_code = ci.lastStatusCode
            self.last_status_text = ci.lastReason

            # Amostra estatísticas finais de mídia antes de fechar
            self.amostrar_rtp()

            # Tenta parar a gravação de mídia
            try:
                parar_gravacao(self)
            except Exception as e:
                pass

            # Registra no painel/memória local
            if hasattr(self, "registrar_resultado"):
                try:
                    self.registrar_resultado()
                except Exception:
                    pass

            # CORREÇÃO 3: Bloco seguro para gravação no SQLite
            try:
                salvar_registro_chamada(
                    self, nome_audio=self.nome_arquivo_audio
                )
                print(
                    f"[SQLite] Chamada para {self.telefone} registrada com sucesso!"
                )
            except Exception as e:
                print(f"[SQLite ERRO] Falha ao gravar chamada no banco: {e}")

    def onCallMediaState(self, prm):
        try:
            reconectar_gravacao(self)
        except Exception:
            pass

    def onCallTsxState(self, prm):
        try:
            ci = self.getInfo()
            codigo = ci.lastStatusCode
            motivo = ci.lastReason

            if codigo and codigo != self._ultimo_codigo_evento:
                t_relativo = (
                    round(time.time() - self.t_invite, 2)
                    if self.t_invite
                    else None
                )
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
                self.sip_mensagem_bruta = texto
            elif src.tdata is not None and src.tdata.wholeMsg:
                texto = src.tdata.wholeMsg

            if texto:
                if self.bina_header_from is None:
                    from_header = extrair_header_sip(texto, "From")
                    if from_header:
                        self.bina_header_from = from_header
                        m = re.search(
                            r"sip:([^@;>]+)@", from_header, re.IGNORECASE
                        )
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
            pdd_s = round(self.t_ring - self.t_invite, 2)

        setup_s = None
        if self.t_invite and self.t_answer:
            setup_s = round(self.t_answer - self.t_invite, 2)

        ring_duration_s = None
        if self.t_ring and self.t_answer:
            ring_duration_s = round(self.t_answer - self.t_ring, 2)

        talk_duration_s = None
        if self.t_answer and self.t_end:
            talk_duration_s = round(self.t_end - self.t_answer, 2)

        total_duration_s = None
        if self.t_invite and self.t_end:
            total_duration_s = round(self.t_end - self.t_invite, 2)

        if getattr(self, "desligamos_local", False):
            release_by = "LOCAL"
        elif self.t_answer is not None:
            release_by = "REMOTE"
        else:
            release_by = "NETWORK"

        jitter_medio_ms = round(self._jitter_medio_usec / 1000, 2) if getattr(self, "_jitter_medio_usec", None) is not None else None
        jitter_maximo_ms = round(self._jitter_maximo_usec / 1000, 2) if getattr(self, "_jitter_maximo_usec", None) is not None else None
        rtt_ms = round(self._rtt_medio_usec / 1000, 2) if getattr(self, "_rtt_medio_usec", None) is not None else None

        packet_loss_pct = None
        pk_loss = getattr(self, "_packet_loss", None)
        pk_rec = getattr(self, "_packets_recebidos", None)
        if pk_loss is not None and pk_rec is not None:
            total_esperado = pk_loss + pk_rec
            if total_esperado > 0:
                packet_loss_pct = round(pk_loss / total_esperado * 100, 2)

        row = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ramal": getattr(self, "ramal", ""),
            "tronco": getattr(self, "operadora", ""),
            "pdd_s": pdd_s,
            "setup_time_s": setup_s,
            "sip_code": getattr(self, "last_status_code", 0),
            "sip_reason": getattr(self, "last_status_text", ""),
            "atendida": self.t_answer is not None,
            "Número": getattr(self, "telefone", ""),
            "batch_id": getattr(self, "batch_id", ""),
            "bina_configurado": getattr(self, "bina_configurado", None),
            "bina_enviado": getattr(self, "bina_enviado", None),
            "bina_header_from": getattr(self, "bina_header_from", None),
            "bina_header_pai": getattr(self, "bina_header_pai", None),
            "bina_header_rpid": getattr(self, "bina_header_rpid", None),
            "sip_events": json.dumps(getattr(self, "eventos_sip", []), ensure_ascii=False),
            "q850_cause": getattr(self, "q850_cause", None),
            "release_by": release_by,
            "release_by_fonte": "inferido",
            "ring_duration_s": ring_duration_s,
            "talk_duration_s": talk_duration_s,
            "total_duration_s": total_duration_s,
            "codec": getattr(self, "codec", None),
            "payload_type": getattr(self, "payload_type", None),
            "packets_enviados": getattr(self, "_packets_enviados", None),
            "packets_recebidos": pk_rec,
            "packet_loss": pk_loss,
            "packet_loss_pct": packet_loss_pct,
            "jitter_medio_ms": jitter_medio_ms,
            "jitter_maximo_ms": jitter_maximo_ms,
            "rtt_ms": rtt_ms,
            "cenario": getattr(self, "cenario", ""),
            "sip_mensagem_bruta": getattr(self, "sip_mensagem_bruta", None),
            "rota": getattr(self, "rota", None),
        }

        # Garante envio do dicionário correto ao painel/banco
        if hasattr(self, "painel") and self.painel:
            self.painel.registrar(dict(row))
            
        return row

        if self.painel:
            self.painel.registrar(row)


def criar_endpoint_e_conta(config, nome_thread="main_thread"):
    ep = pj.Endpoint()
    ep.libCreate()

    ep_cfg = pj.EpConfig()
    log_cfg = ep_cfg.logConfig
    log_cfg.level = 4
    log_cfg.consoleLevel = 4
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
    ramal = config["ramal"]
    sip_domain = config["sip_domain"]
    cenario = config.get("cenario", "ligado")
    tech_por_operadora = config.get("tech_por_operadora", {})
    batch_id = gerar_batch_id()
    Console.print(f"[bold cyan]Batch: {batch_id} — cenário: {cenario}")

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

            # Callback de progresso seguro (garante dados isolados e não tuplas soltas)
            if on_progresso is not None:
                try:
                    on_progresso(destino, operadora, "iniciando")
                except Exception as err_prog:
                    Console.print(f"[bold yellow]Aviso no callback de progresso (iniciando): {err_prog}")

            numero_fical = numero_discagem(operadora, destino, tech_por_operadora)
            rota = tech_por_operadora.get(operadora, TECH_PADRAO)

            call = TesteCall(
                acc=acc,
                call_id=pj.PJSUA_INVALID_ID,
                operadora=operadora,
                telefone=destino,
                ip=sip_domain,
                ramal=ramal,
                painel=painel,
                batch_id=batch_id,
                cenario=cenario,
                rota=rota,
            )

            call_prm = pj.CallOpParam(True)
            dst_uri = f"sip:{numero_fical}@{sip_domain}"

            # 2. CAPTURAR ERROS NATIVOS DO C++ NO MAKECALL
            try:
                call.makeCall(dst_uri, call_prm)
            except pj.Error as e:
                Console.print(f"[bold red]Erro ao disparar makeCall para {dst_uri}: {e.info()}")
                # Registra falha de disparo direto no CDR/Painel em formato de dicionário
                if hasattr(call, "registrar_resultado"):
                    call.last_status_code = 500
                    call.last_status_text = f"Erro PJSIP: {e.info()}"
                    call.registrar_resultado()
                continue

            # 3. BOMBEAR EVENTOS DO PJSIP NO LOOP DE ESPERA
            proxima_amostra_rtp = 0.0
            while True:
                try:
                    ep.libHandleEvents(50)  # Mantém a pilha SIP ativa

                    # Validação segura do estado da chamada
                    try:
                        ci = call.getInfo()
                        state = ci.state
                    except pj.Error:
                        # Se a chamada já foi destruída na memória C++, interrompe o loop
                        break

                    if state >= pj.PJSIP_INV_STATE_DISCONNECTED:
                        break

                    # Amostra RTP/codec ~1x por segundo enquanto atendida
                    if state == pj.PJSIP_INV_STATE_CONFIRMED:
                        agora = time.time()
                        if agora >= proxima_amostra_rtp:
                            if hasattr(call, "amostrar_rtp"):
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

            # Garante que a pilha do PJSIP processe eventos residuais do desligamento
            for _ in range(10):
                ep.libHandleEvents(10)

            # Garantia final: Força o registro do CDR caso o callback de estado não tenha acionado
            if hasattr(call, "resultado_registrado") and not call.resultado_registrado:
                if hasattr(call, "registrar_resultado"):
                    call.registrar_resultado()

            Console.print(f"[bold red]Teste com {operadora} finalizado. Pausando 2 segundos...")

            if on_progresso is not None:
                try:
                    on_progresso(destino, operadora, "concluido")
                except Exception as err_prog:
                    Console.print(f"[bold yellow]Aviso no callback de progresso (concluido): {err_prog}")

            time.sleep(2)

        Console.print(f"\n[bold red][CONCLUÍDO] Todos os testes para o número {destino} foram finalizados.")
        time.sleep(3)

    Console.print("\n[bold red]Fila geral de chamadas concluída. Todos os dados foram salvos.")

def main():
    init_db()
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