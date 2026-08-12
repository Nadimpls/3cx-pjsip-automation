import csv
import os
import time
import pjsua2 as pj
from gravador import iniciar_gravacao, parar_gravacao
from rich.console import Console
from registro import PainelAoVivo  # <--- Importa o painel ao vivo que criamos

Console = Console()

TECH = "170"

TRONCO_OPERADORAS = {
    "OTIMA": "2223",
    "PRIMACOM": "2224",
    "OKTOR": "2225",
    "AGIL": "2226",
    "EMBRATEL": "2221"
}

CODIGO_ROTA = "5060"

def numero_discagem(operadora, numero_ddd):
    tronco = TRONCO_OPERADORAS.get(operadora)
    if tronco is None:
        raise ValueError(f"OPERADORA '{operadora}' não identificada em TRONCO_OPERADORAS")
    return f"{TECH}{tronco}{numero_ddd}"


class TesteCall(pj.Call):

    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, operadora=None, telefone=None, ip=None, ramal=None, painel=None):
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

    def registrar_resultado(self):
        pdd_s = None
        if self.t_invite and self.t_ring:
            pdd_s = round(self.t_ring - self.t_invite, 2)  # Segundos com 2 casas decimais

        setup_s = None
        if self.t_invite and self.t_answer:
            setup_s = round(self.t_answer - self.t_invite, 2)

        row = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ramal": self.ramal,
            "tronco": self.operadora,
            "pdd_s": pdd_s,
            "setup_time_s": setup_s,
            "sip_code": self.last_status_code,
            "sip_reason": self.last_status_text,
            "atendida": self.t_answer is not None,
            "Número": self.telefone
        }

        # Envia os dados para o painel atualizar a tabela e salvar no CSV automaticamente
        if self.painel:
            self.painel.registrar(row)


def main():
    ep = pj.Endpoint()
    ep.libCreate()

    ep_cfg = pj.EpConfig()
    log_cfg = ep_cfg.logConfig
    log_cfg.level = 4
    log_cfg.consoleLevel = 4
    ep.libInit(ep_cfg)

    sip_tp_cfg = pj.TransportConfig()
    sip_tp_cfg.port = 5060 
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, sip_tp_cfg)

    ep.libStart()

    ep.libRegisterThread("main_thread")

    SIP_DOMAIN = "172.17.192.100"
    RAMAL = "9200"
    AUTH_ID = "9200"
    SENHA = "54321"
    
    LISTA_DESTINOS = [
        "41988404022"
    ]
    
    OPERADORAS_TESTE = ["OTIMA", "PRIMACOM", "OKTOR", "AGIL", "EMBRATEL"]

    acc_cfg = pj.AccountConfig()
    acc_cfg.idUri = f"sip:{RAMAL}@{SIP_DOMAIN}"
    acc_cfg.regConfig.registrarUri = f"sip:{SIP_DOMAIN}"

    cred = pj.AuthCredInfo("digest", "*", AUTH_ID, 0, SENHA)
    acc_cfg.sipConfig.authCreds.append(cred)

    acc = pj.Account()
    acc.create(acc_cfg)

    time.sleep(2)

    # ATIVA O PAINEL AO VIVO DO RICH ENQUANTO RODE AS CHAMADAS
    with PainelAoVivo() as painel:
        
        # LOOP 1: Percorre cada número da lista de destinos
        for destino in LISTA_DESTINOS:
            Console.print(f"\n[bold red] ========================================")
            Console.print(f"[bold red] INICIANDO TESTES PARA O NÚMERO: {destino}")
            Console.print(f"[bold red] ========================================")
            
            # LOOP 2: Para cada número, testa todas as operadoras em sequência
            for operadora in OPERADORAS_TESTE:
                Console.print(f"\n[bold cyan]--- Testando operadora: {operadora} para o número {destino} ---")
                
                numero_fical = numero_discagem(operadora, destino)
                
                call = TesteCall(
                    acc=acc,
                    call_id=pj.PJSUA_INVALID_ID,
                    operadora=operadora,
                    telefone=destino,
                    ip=SIP_DOMAIN,
                    ramal=RAMAL,
                    painel=painel   # <--- Passando o painel para a chamada
                )
                
                call_prm = pj.CallOpParam(True)
                dst_uri = f"sip:{numero_fical}@{SIP_DOMAIN}"

                # 2. CAPTURAR ERROS NATIVOS DO C++
                try:
                    call.makeCall(dst_uri, call_prm)
                except pj.Error as e:
                    Console.print(f"[bold red]Erro ao disparar makeCall para {dst_uri}: {e.info()}")
                    continue

                # 3. BOMBEAR EVENTOS DO PJSIP NO LOOP DE ESPERA
                while True:
                    try:
                        ep.libHandleEvents(50)  # Mantém a pilha SIP ativa e escutando a rede
                        state = call.getInfo().state
                        if state >= pj.PJSIP_INV_STATE_DISCONNECTED:
                            break
                    except Exception as err:
                        Console.print(f"[bold yellow]Exceção no monitoramento da chamada: {err}")
                        break

                Console.print(f"[bold red]Teste com {operadora} finalizado. Pausando 2 segundos...")
                time.sleep(2)

            Console.print(f"\n[bold red][CONCLUÍDO] Todos os testes para o número {destino} foram finalizados.")
            time.sleep(3)

    Console.print("\n[bold red]Fila geral de chamadas concluída. Todos os dados foram salvos no CSV e áudios na pasta.")


if __name__ == "__main__":
    main()