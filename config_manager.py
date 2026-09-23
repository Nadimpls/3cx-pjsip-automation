import json
import os
from cryptography.fernet import Fernet

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
KEY_PATH = os.path.join(BASE_DIR, "secret.key")

OPERADORAS_DISPONIVEIS = ["OTIMA", "PRIMACOM", "OKTOR", "AGIL", "EMBRATEL", "LEMIT"]

CONFIG_PADRAO = {
    "sip_domain": "172.17.192.100",
    "porta_sip": 5060,
    "ramal": "9201",
    "auth_id": "9201",
    "senha_cifrada": None,
    "operadoras_habilitadas": list(OPERADORAS_DISPONIVEIS),
    "destinos": ["41988404022"],
}

_SENHA_PADRAO = "9201"  # semente usada só na primeira criação do config.json


def _obter_fernet():
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            chave = f.read()
    else:
        chave = Fernet.generate_key()
        with open(KEY_PATH, "wb") as f:
            f.write(chave)
    return Fernet(chave)


def _cifrar_senha(senha_texto_puro):
    return _obter_fernet().encrypt(senha_texto_puro.encode("utf-8")).decode("utf-8")


def _decifrar_senha(senha_cifrada):
    return _obter_fernet().decrypt(senha_cifrada.encode("utf-8")).decode("utf-8")


def carregar_config():
    if not os.path.exists(CONFIG_PATH):
        config = dict(CONFIG_PADRAO)
        config["senha_cifrada"] = _cifrar_senha(_SENHA_PADRAO)
        salvar_config_bruto(config)
        return config

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    for chave, valor in CONFIG_PADRAO.items():
        config.setdefault(chave, valor)
    return config


def salvar_config_bruto(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def salvar_config(dados_novos):
    """Mescla dados_novos na config atual. Se 'senha' (texto puro) vier em
    dados_novos, ela é cifrada e substitui senha_cifrada; se vier vazia ou
    ausente, a senha já salva é preservada."""
    config = carregar_config()

    senha_texto_puro = dados_novos.pop("senha", None)

    for chave in ("sip_domain", "porta_sip", "ramal", "auth_id"):
        if chave in dados_novos:
            config[chave] = dados_novos[chave]

    if "operadoras_habilitadas" in dados_novos:
        config["operadoras_habilitadas"] = [
            op for op in dados_novos["operadoras_habilitadas"] if op in OPERADORAS_DISPONIVEIS
        ]

    if "destinos" in dados_novos:
        config["destinos"] = [d.strip() for d in dados_novos["destinos"] if d.strip()]

    if senha_texto_puro:
        config["senha_cifrada"] = _cifrar_senha(senha_texto_puro)

    salvar_config_bruto(config)
    return config


def obter_senha(config=None):
    """Só deve ser usada no backend, ao montar o AuthCredInfo do PJSUA2."""
    config = config or carregar_config()
    if not config.get("senha_cifrada"):
        return ""
    return _decifrar_senha(config["senha_cifrada"])


def config_publica(config=None):
    """Versão da config segura para expor pela API: nunca inclui a senha."""
    config = config or carregar_config()
    publica = dict(config)
    publica["senha_definida"] = bool(publica.pop("senha_cifrada", None))
    return publica
