import time
import pjsua2 as pj
import config as c
from gravador import iniciar_gravacao, parar_gravacao
from classificador import classificar_chamada


def numero_discagem(operadora, numero_ddd):
    tronco = c.TRONCO_OPERADORAS.get(operadora)
    if tronco is None:
        raise ValueError(f"OPERADORA '{operadora}' não identificada em TRONCO_OPERADORAS")
    return f"{c.TECH}{tronco}{numero_ddd}"


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
        self.tipo_teste = "padrao"
        self.meta_extra = {}
        self.audio_path = None  # caminho do WAV gravado

    def onCallState(self, prm):
        """Callback executado pelo PJSIP sempre que o estado da chamada muda."""
        try:
            ci = self.getInfo()
            now = time.time()

            # 1. CAPTURA DOS DADOS SIP
            status_texto = ci.stateText if ci.stateText else "INICIANDO"
            codigo_sip = f"{ci.lastStatusCode} {ci.lastReason}".strip()
            if not ci.lastStatusCode:
                codigo_sip = "Sinalizando..."

            # 2. ATUALIZAÇÃO EM TEMPO REAL DO PAINEL
            if self.painel:
                self.painel.atualizar(
                    ramal=str(self.ramal),
                    destino=str(self.telefone),
                    operadora=str(self.operadora),
                    status=str(status_texto),
                    codigo_sip=str(codigo_sip),
                )

            # 3. LÓGICA DE MÁQUINA DE ESTADOS SIP
            if ci.state == pj.PJSIP_INV_STATE_CALLING:
                self.t_invite = now

            elif ci.state == pj.PJSIP_INV_STATE_EARLY:
                if self.t_ring is None:
                    self.t_ring = now
                    self.last_status_code = ci.lastStatusCode
                    self.last_status_text = ci.lastReason

            elif ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
                self.t_answer = now
                nome_arquivo = (
                    f"{self.operadora}_{self.telefone}_{time.strftime('%Y%m%d_%H%M%S')}.wav"
                )
                print(f"\n[PJSIP] 📞 Chamada atendida! Gravando áudio em: {nome_arquivo}")
                self.audio_path = iniciar_gravacao(self, file_path=nome_arquivo)

            elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.t_end = now
                self.last_status_code = ci.lastStatusCode
                self.last_status_text = ci.lastReason

                # Fecha o arquivo WAV primeiro para liberar para o Whisper
                print("[PJSIP] 📴 Chamada desligada. Encerrando gravação...")
                parar_gravacao(self)

                # Processa a classificação e salva os resultados
                self.registrar_resultado()

        except Exception as e:
            print(f"[ERRO NO ONCALLSTATE]: {e}")

    def registrar_resultado(self):
        pdd_s = None
        if self.t_invite and self.t_ring:
            pdd_s = round(self.t_ring - self.t_invite, 2)

        setup_s = None
        if self.t_invite and self.t_answer:
            setup_s = round(self.t_answer - self.t_invite, 2)

        print(f"[ANALISE] 🔍 Iniciando classificação do áudio ({self.audio_path})...")

        # Classificação do áudio gravado via Whisper
        resultado_classificacao = classificar_chamada(self, audio_path=self.audio_path)

        print(f"[ANALISE] ✅ Resultado: {resultado_classificacao['classificacao']} | Motivo: {resultado_classificacao['motivo_classificacao']}")
        if resultado_classificacao.get("transcricao"):
            print(f"[ANALISE] 📝 Transcrição: '{resultado_classificacao['transcricao']}'")

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
            "classificacao": resultado_classificacao["classificacao"],
            "motivo_classificacao": resultado_classificacao["motivo_classificacao"],
            "audio_duration_s": resultado_classificacao["audio_duration_s"],
        }

        # Envia os dados para o painel atualizar a tabela e salvar no CSV
        if self.painel and hasattr(self.painel, "registrar"):
            self.painel.registrar(row)