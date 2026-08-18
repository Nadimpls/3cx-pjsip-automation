# -*- coding: utf-8 -*-
import importlib.util
import os
import sys

# --- CONFIGURAÇÃO DE CARREGAMENTO DAS DLLS E MÓDULO _pjsua2 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Registra os diretórios de DLLs para Windows/MINGW no carregador nativo do Python
if hasattr(os, "add_dll_directory"):
  # Pasta raiz do projeto
  os.add_dll_directory(BASE_DIR)

  # Adiciona os binários nativos do MinGW64 do MSYS2 (onde ficam libwinpthread-1.dll, libstdc++-6.dll, etc.)
  msys_bin = r"C:\msys64\mingw64\bin"
  if os.path.exists(msys_bin):
    os.add_dll_directory(msys_bin)

  # Pasta de pacotes do ambiente virtual
  site_pkg = os.path.join(BASE_DIR, "venv_win", "Lib", "site-packages")
  if os.path.exists(site_pkg):
    os.add_dll_directory(site_pkg)

# 2. Garante a importação do _pjsua2 (captura tanto ModuleNotFoundError quanto ImportError)
try:
  import _pjsua2
except (ModuleNotFoundError, ImportError) as err:
  site_pkg = os.path.join(BASE_DIR, "venv_win", "Lib", "site-packages")

  pyd_found = None
  if os.path.exists(site_pkg):
    for f in os.listdir(site_pkg):
      if f.startswith("_pjsua2") and f.endswith(".pyd"):
        pyd_found = os.path.join(site_pkg, f)
        break

  if pyd_found:
    spec = importlib.util.spec_from_file_location("_pjsua2", pyd_found)
    _pjsua2 = importlib.util.module_from_spec(spec)
    sys.modules["_pjsua2"] = _pjsua2
    spec.loader.exec_module(_pjsua2)
  else:
    raise err

import time
import pjsua2 as pj

import baterias.rate_sensitivity as b_rate
import baterias.reattach as b_reattach
from classificador import classificar_chamada
import config as c
from registro import PainelAoVivo
from teste import TesteCall


def emitir_log(texto, log_callback=None):
  """Envia a mensagem para a GUI (se fornecido) e/ou imprime no terminal."""
  if log_callback:
    log_callback(texto)
  else:
    print(texto)


def disparar_e_aguardar(
    ep, acc, operadora, destino, ramal, painel, sip_domain, log_callback=None
):
  emitir_log(f"--- Testando {operadora} -> {destino} ---", log_callback)

  tronco = c.TRONCO_OPERADORAS.get(operadora)
  if not tronco:
    emitir_log(
        f"[ERRO] Operadora '{operadora}' não encontrada em TRONCO_OPERADORAS",
        log_callback,
    )
    return

  numero_fical = f"{c.TECH}{tronco}{destino}"
  call = TesteCall(
      acc=acc,
      call_id=pj.PJSUA_INVALID_ID,
      operadora=operadora,
      telefone=destino,
      ip=c.SIP_DOMAIN,
      ramal=ramal,
      painel=painel,
  )

  call_prm = pj.CallOpParam(True)
  dst_uri = f"sip:{numero_fical}@{sip_domain}"

  try:
    call.makeCall(dst_uri, call_prm)
  except pj.Error as e:
    emitir_log(f"[ERRO] makeCall para {dst_uri}: {e.info()}", log_callback)
    return

  while True:
    try:
      ep.libHandleEvents(50)
      state = call.getInfo().state
      if state >= pj.PJSIP_INV_STATE_DISCONNECTED:
        break
    except Exception as err:
      emitir_log(f"[EXCEÇÃO] {err}", log_callback)
      break

  caminho_audio = getattr(call, "wav_path", f"gravacao_{destino}.wav")
  if os.path.exists(caminho_audio):
    emitir_log("🔍 Analisando áudio com Whisper...", log_callback)
    resultado = classificar_chamada(call, audio_path=caminho_audio)
    emitir_log(
        f"Classificação: {resultado['classificacao']} | Motivo:"
        f" {resultado['motivo_classificacao']}",
        log_callback,
    )
  else:
    resultado = classificar_chamada(call, audio_path=None)
    emitir_log(
        f"Classificação SIP: {resultado['classificacao']}", log_callback
    )


def executar_automacao(
    modo="padrao", log_callback=None, app_state=None, painel_factory=None
):
  """Função principal chamada pela GUI/TUI ou via terminal.

  painel_factory: callable opcional que retorna um objeto com a mesma
  interface de PainelAoVivo (atualizar/registrar/__enter__/__exit__).
  Usado pela interface Textual (tui_painel.PainelTUI) para desviar as
  atualizações para a UI em vez de desenhar a tabela Rich sozinho.
  Se não for passado, mantém o comportamento original (PainelAoVivo).
  """
  emitir_log(f"[+] Inicializando PJSIP no modo '{modo}'...", log_callback)

  ep = pj.Endpoint()
  ep.libCreate()

  ep_cfg = pj.EpConfig()
  ep_cfg.logConfig.level = 4
  ep_cfg.logConfig.consoleLevel = 0
  ep.libInit(ep_cfg)

  sip_tp_cfg = pj.TransportConfig()
  sip_tp_cfg.port = 5060
  ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, sip_tp_cfg)

  ep.libStart()
  # Registra a thread atual junto ao pjsua2 — importante quando executar_automacao
  # roda dentro de uma thread de worker (caso da interface Textual), e não na
  # thread principal do processo.
  ep.libRegisterThread("automacao_thread")

  acc_cfg = pj.AccountConfig()
  acc_cfg.idUri = f"sip:{c.RAMAL}@{c.SIP_DOMAIN}"
  acc_cfg.regConfig.registrarUri = f"sip:{c.SIP_DOMAIN}"
  cred = pj.AuthCredInfo("digest", "*", c.AUTH_ID, 0, c.SENHA)
  acc_cfg.sipConfig.authCreds.append(cred)

  acc = pj.Account()
  acc.create(acc_cfg)
  time.sleep(2)

  criar_painel = painel_factory if painel_factory else PainelAoVivo

  try:
    with criar_painel() as painel:
      total = len(c.LISTA_DESTINOS) * len(c.OPERADORAS_TESTE)
      contador = 0

      for destino in c.LISTA_DESTINOS:
        for operadora in c.OPERADORAS_TESTE:
          # Checa se o usuário clicou em Parar na interface
          if app_state and not app_state.get("running", True):
            emitir_log("[!] Teste interrompido pelo usuário.", log_callback)
            return

          contador += 1
          emitir_log(
              f"\n>>> CICLO {contador}/{total} | {operadora} -> {destino}",
              log_callback,
          )

          if modo == "padrao":
            disparar_e_aguardar(
                ep,
                acc,
                operadora,
                destino,
                c.RAMAL,
                painel,
                c.SIP_DOMAIN,
                log_callback,
            )
            time.sleep(2)

          elif modo == "rate_sensitivity":
            b_rate.bateria_rate_sensitivity(
                ep, acc, destino, operadora, c.RAMAL, painel, c.SIP_DOMAIN
            )

          elif modo == "reattach":
            b_reattach.bateria_reattach_manual(
                ep,
                acc,
                destino,
                operadora,
                c.RAMAL,
                painel,
                c.SIP_DOMAIN,
                ciclo_atual=contador,
                ciclo_total=total,
            )

  finally:
    emitir_log("[+] Encerrando PJSIP...", log_callback)
    ep.libDestroy()


if __name__ == "__main__":
  executar_automacao(modo="rate_sensitivity")