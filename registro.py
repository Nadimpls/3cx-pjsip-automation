import csv
import os
import re
import threading
import time
from rich.console import Console
from rich.table import Table
from rich.live import Live

console = Console()

CAMPOS_CSV = [
    "timestamp",
    "ramal",
    "tronco",
    "pdd_s",
    "setup_time_s",
    "sip_code",
    "sip_reason",
    "atendida",
    "Número",
    "batch_id",
    "bina_configurado",
    "bina_enviado",
    "bina_header_from",
    "bina_header_pai",
    "bina_header_rpid",
    "sip_events",
    "q850_cause",
    "release_by",
    "release_by_fonte",
    "ring_duration_s",
    "talk_duration_s",
    "total_duration_s",
    "codec",
    "payload_type",
    "packets_enviados",
    "packets_recebidos",
    "packet_loss",
    "packet_loss_pct",
    "jitter_medio_ms",
    "jitter_maximo_ms",
    "rtt_ms",
    "bina_manual",
    "spam",
    "cenario",
    "sip_mensagem_bruta",
    "rota",
]

CENARIOS_VALIDOS = ("ligado", "desligado")


def extrair_header_sip(texto_sip, nome_header):
    """Pega o valor de um header específico de um texto SIP cru (o próprio
    PJSUA2 entrega isso via wholeMsg — isto é só um parsing leve em cima do
    que ele já forneceu, não é uma captura SIP paralela). Retorna None se o
    header não existir ou o texto for vazio."""
    if not texto_sip:
        return None
    m = re.search(rf'^{re.escape(nome_header)}\s*:\s*(.+)$', texto_sip, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def extrair_q850_cause(texto_sip):
    """Pega a causa Q.850 de um header 'Reason: Q.850;cause=NN;...', quando
    o PABX/operadora incluir esse header. Retorna None se não encontrar."""
    valor_reason = extrair_header_sip(texto_sip, "Reason")
    if not valor_reason or "q.850" not in valor_reason.lower():
        return None
    m = re.search(r"cause\s*=\s*(\d+)", valor_reason, re.IGNORECASE)
    return m.group(1) if m else None


def registrar_resultado(self):
    pdd_s = None
    if self.t_invite and self.t_ring:
        pdd_s = round(self.t_ring - self.t_invite, 2)

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

    if self.painel:
        self.painel.registrar(row)


def montar_tabela(chamadas):
    tabela = Table(title="Monitor de Chamadas PJSIP ao Vivo")
    tabela.add_column("Horário")
    tabela.add_column("Ramal")
    tabela.add_column("Tronco")
    tabela.add_column("PDD (s)")
    tabela.add_column("Status SIP")
    tabela.add_column("Atendida")
    tabela.add_column("Número")

    for c in chamadas:
        cor = "green" if c.get("sip_code") == 200 else "red"
        tabela.add_row(
            str(c.get("timestamp", "")),
            str(c.get("ramal", "")),
            str(c.get("tronco", "")),
            str(c.get("pdd_s", "")),
            f"[{cor}]{c.get('sip_code', '')}[/{cor}]",
            str(c.get("atendida", "")),
            str(c.get("Número", ""))
        )
    return tabela


def _migrar_cabecalho_se_necessario(caminho_completo):
    with open(caminho_completo, "r", newline="", encoding="utf-8") as f:
        primeira_linha = f.readline()
        if not primeira_linha:
            return
        cabecalho_atual = next(csv.reader([primeira_linha]))
        if cabecalho_atual == CAMPOS_CSV:
            return
        resto_do_arquivo = f.read()

    with open(caminho_completo, "w", newline="", encoding="utf-8") as f:
        f.write(",".join(CAMPOS_CSV) + "\n")
        f.write(resto_do_arquivo)


def salvar_csv(row, caminho="resultado_pdd.csv"):
    try:
        diretorio_atual = os.path.dirname(os.path.abspath(__file__))
        caminho_completo = os.path.join(diretorio_atual, caminho)

        arquivo_existe = os.path.exists(caminho_completo)

        if arquivo_existe and os.path.getsize(caminho_completo) > 0:
            _migrar_cabecalho_se_necessario(caminho_completo)

        with open(caminho_completo, "a", newline="", encoding="utf-8") as f:
            # Usa a lista padrão CAMPOS_CSV para manter a ordem correta das colunas
            writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
            if not arquivo_existe or f.tell() == 0:
                writer.writeheader()
            writer.writerow(row)
            
        console.print(f"[dim green][CSV] Linha salva com sucesso.[/dim green]")
        
    except Exception as e:
        console.print(f"[bold red][ERRO AO SALVAR CSV]: {e}[/bold red]")


class PainelAoVivo:

    def __init__(self):
        self.chamadas = []
        self.live = Live(montar_tabela(self.chamadas), console=console, refresh_per_second=4)

    def __enter__(self):
        self.live.start()
        return self

    def __exit__(self, *exc):
        self.live.stop()

    def registrar(self, row):
        self.chamadas.append(row)
        salvar_csv(row)
        self.live.update(montar_tabela(self.chamadas))


CAMINHO_CSV_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultado_pdd.csv")


def ler_todos_resultados(caminho=CAMINHO_CSV_PADRAO):
    if not os.path.exists(caminho):
        return []
    with open(caminho, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def atualizar_campos_chamada(timestamp, tronco, numero, campos, caminho=CAMINHO_CSV_PADRAO):
    if not os.path.exists(caminho):
        return False

    linhas = ler_todos_resultados(caminho)
    encontrada = None
    for linha in linhas:
        if (linha.get("timestamp") == timestamp
                and linha.get("tronco") == tronco
                and linha.get("Número") == numero):
            encontrada = linha
            break

    if encontrada is None:
        return False

    encontrada.update(campos)

    with open(caminho, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        writer.writeheader()
        for linha in linhas:
            writer.writerow({campo: linha.get(campo) for campo in CAMPOS_CSV})

    return True


def gerar_batch_id(caminho=CAMINHO_CSV_PADRAO):
    hoje = time.strftime("%Y%m%d")
    prefixo = f"BATCH-{hoje}-"
    existentes = {
        linha.get("batch_id")
        for linha in ler_todos_resultados(caminho)
        if (linha.get("batch_id") or "").startswith(prefixo)
    }
    return f"{prefixo}{len(existentes) + 1:03d}"


def dias_disponiveis(caminho=CAMINHO_CSV_PADRAO):

    contagem = {}
    for linha in ler_todos_resultados(caminho):
        data = (linha.get("timestamp") or "")[:10]
        if not data:
            continue
        contagem[data] = contagem.get(data, 0) + 1
    return [
        {"data": data, "quantidade": contagem[data]}
        for data in sorted(contagem.keys(), reverse=True)
    ]


def resultados_do_dia(data, caminho=CAMINHO_CSV_PADRAO):

    return [
        linha for linha in ler_todos_resultados(caminho)
        if (linha.get("timestamp") or "").startswith(data)
    ]


_PADRAO_NOME_AUDIO = re.compile(r"^(.+)_(\d+)_(\d{8})_(\d{6})\.wav$", re.IGNORECASE)


def resultados_do_dia_com_audio(data, audios_dir, caminho=CAMINHO_CSV_PADRAO):

    linhas = resultados_do_dia(data, caminho)

    data_compacta = data.replace("-", "")
    grupos_audio = {}
    if os.path.isdir(audios_dir):
        for nome in os.listdir(audios_dir):
            m = _PADRAO_NOME_AUDIO.match(nome)
            if not m:
                continue
            operadora, numero, data_arquivo, hora_arquivo = m.groups()
            if data_arquivo != data_compacta:
                continue
            chave = (operadora, numero)
            grupos_audio.setdefault(chave, []).append((hora_arquivo, nome))

    for chave in grupos_audio:
        grupos_audio[chave].sort()

    indices = {chave: 0 for chave in grupos_audio}

    for linha in linhas:
        linha["arquivo_audio"] = None
        atendida = str(linha.get("atendida", "")).strip().lower() == "true"
        chave = (linha.get("tronco"), linha.get("Número"))
        if atendida and chave in grupos_audio:
            i = indices[chave]
            if i < len(grupos_audio[chave]):
                linha["arquivo_audio"] = grupos_audio[chave][i][1]
                indices[chave] += 1

    return linhas


def audios_do_dia(data, audios_dir):

    data_compacta = data.replace("-", "")
    encontrados = []
    if os.path.isdir(audios_dir):
        for nome in os.listdir(audios_dir):
            m = _PADRAO_NOME_AUDIO.match(nome)
            if m and m.group(3) == data_compacta:
                encontrados.append((m.group(4), nome))
    encontrados.sort(reverse=True)
    return [nome for _, nome in encontrados]


def _para_float(valor):

    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _percentil(valores_ordenados, p):

    if not valores_ordenados:
        return None
    if len(valores_ordenados) == 1:
        return valores_ordenados[0]
    k = (len(valores_ordenados) - 1) * (p / 100)
    piso = int(k)
    teto = min(piso + 1, len(valores_ordenados) - 1)
    if piso == teto:
        return valores_ordenados[piso]
    return valores_ordenados[piso] + (valores_ordenados[teto] - valores_ordenados[piso]) * (k - piso)


def _stat_lista(valores):
    if not valores:
        return {"media": None, "mediana": None, "p95": None, "minimo": None, "maximo": None}
    ordenados = sorted(valores)
    return {
        "media": round(sum(valores) / len(valores), 2),
        "mediana": round(_percentil(ordenados, 50), 2),
        "p95": round(_percentil(ordenados, 95), 2),
        "minimo": round(ordenados[0], 2),
        "maximo": round(ordenados[-1], 2),
    }


def _filtrar_linhas(linhas, data=None, cenario=None):

    if data:
        linhas = [l for l in linhas if (l.get("timestamp") or "").startswith(data)]
    if cenario:
        linhas = [l for l in linhas if (l.get("cenario") or "ligado") == cenario]
    return linhas


def estatisticas_por_operadora(caminho=CAMINHO_CSV_PADRAO, data=None, cenario=None):

    linhas = _filtrar_linhas(ler_todos_resultados(caminho), data=data, cenario=cenario)

    por_operadora = {}
    for linha in linhas:
        tronco = linha.get("tronco") or "N/D"
        por_operadora.setdefault(tronco, []).append(linha)

    resultado = []
    for tronco, grupo in sorted(por_operadora.items()):
        total = len(grupo)
        atendidas = [l for l in grupo if str(l.get("atendida", "")).strip().lower() == "true"]

        pdds = [v for v in (_para_float(l.get("pdd_s")) for l in grupo) if v is not None]
        setups = [v for v in (_para_float(l.get("setup_time_s")) for l in grupo) if v is not None]
        talks = [v for v in (_para_float(l.get("talk_duration_s")) for l in atendidas) if v is not None]

        distribuicao_sip = {}
        for l in grupo:
            codigo = l.get("sip_code") or "N/D"
            distribuicao_sip[codigo] = distribuicao_sip.get(codigo, 0) + 1

        resultado.append({
            "operadora": tronco,
            "total_testes": total,
            "atendidas": len(atendidas),
            "nao_atendidas": total - len(atendidas),
            "asr_pct": round(len(atendidas) / total * 100, 2) if total else None,
            "pdd": _stat_lista(pdds),
            "setup": _stat_lista(setups),
            "acd_s": round(sum(talks) / len(talks), 2) if talks else None,
            "distribuicao_sip": distribuicao_sip,
        })

    return resultado


def estatisticas_por_dia(operadora, caminho=CAMINHO_CSV_PADRAO, cenario=None):
    """Evolução dia a dia de uma operadora específica (ASR, PDD médio,
    Setup médio por data), mais antiga primeiro — pra comparar períodos."""
    linhas = _filtrar_linhas(ler_todos_resultados(caminho), cenario=cenario)
    linhas = [l for l in linhas if l.get("tronco") == operadora]

    por_dia = {}
    for linha in linhas:
        data = (linha.get("timestamp") or "")[:10]
        if not data:
            continue
        por_dia.setdefault(data, []).append(linha)

    resultado = []
    for data in sorted(por_dia.keys()):
        grupo = por_dia[data]
        total = len(grupo)
        atendidas = [l for l in grupo if str(l.get("atendida", "")).strip().lower() == "true"]
        pdds = [v for v in (_para_float(l.get("pdd_s")) for l in grupo) if v is not None]
        setups = [v for v in (_para_float(l.get("setup_time_s")) for l in grupo) if v is not None]

        resultado.append({
            "data": data,
            "total_testes": total,
            "atendidas": len(atendidas),
            "asr_pct": round(len(atendidas) / total * 100, 2) if total else None,
            "pdd_medio": round(sum(pdds) / len(pdds), 2) if pdds else None,
            "setup_medio": round(sum(setups) / len(setups), 2) if setups else None,
        })

    return resultado


def chamadas_por_operadora(operadora, caminho=CAMINHO_CSV_PADRAO, cenario=None):
    linhas = _filtrar_linhas(ler_todos_resultados(caminho), cenario=cenario)
    linhas = [l for l in linhas if l.get("tronco") == operadora]
    linhas.sort(key=lambda l: l.get("timestamp") or "")

    return [
        {
            "timestamp": l.get("timestamp"),
            "atendida": str(l.get("atendida", "")).strip().lower() == "true",
            "pdd_s": _para_float(l.get("pdd_s")),
            "setup_time_s": _para_float(l.get("setup_time_s")),
        }
        for l in linhas
    ]


def chamadas_todas_operadoras(caminho=CAMINHO_CSV_PADRAO, cenario=None):
    linhas = _filtrar_linhas(ler_todos_resultados(caminho), cenario=cenario)
    linhas.sort(key=lambda l: l.get("timestamp") or "")

    return [
        {
            "timestamp": l.get("timestamp"),
            "tronco": l.get("tronco"),
            "atendida": str(l.get("atendida", "")).strip().lower() == "true",
            "pdd_s": _para_float(l.get("pdd_s")),
            "setup_time_s": _para_float(l.get("setup_time_s")),
        }
        for l in linhas
    ]


def evolucao_todas_operadoras(caminho=CAMINHO_CSV_PADRAO, cenario=None):
    linhas = _filtrar_linhas(ler_todos_resultados(caminho), cenario=cenario)

    por_dia_operadora = {}
    for linha in linhas:
        data = (linha.get("timestamp") or "")[:10]
        tronco = linha.get("tronco") or "N/D"
        if not data:
            continue
        por_dia_operadora.setdefault(data, {}).setdefault(tronco, []).append(linha)

    resultado = []
    for data in sorted(por_dia_operadora.keys()):
        operadoras = {}
        for tronco, grupo in por_dia_operadora[data].items():
            total = len(grupo)
            atendidas = [l for l in grupo if str(l.get("atendida", "")).strip().lower() == "true"]
            pdds = [v for v in (_para_float(l.get("pdd_s")) for l in grupo) if v is not None]
            setups = [v for v in (_para_float(l.get("setup_time_s")) for l in grupo) if v is not None]
            operadoras[tronco] = {
                "total_testes": total,
                "atendidas": len(atendidas),
                "asr_pct": round(len(atendidas) / total * 100, 2) if total else None,
                "pdd_medio": round(sum(pdds) / len(pdds), 2) if pdds else None,
                "setup_medio": round(sum(setups) / len(setups), 2) if setups else None,
            }
        resultado.append({"data": data, "operadoras": operadoras})

    return resultado


class PainelWeb:
    
    def __init__(self):
        self._lock = threading.Lock()
        self.chamadas = []

    def registrar(self, row):
        salvar_csv(row)
        with self._lock:
            self.chamadas.append(row)

    def adicionar_resultado(self, row):

        with self._lock:
            self.chamadas.append(row)

    def obter_resultados(self):
        with self._lock:
            return list(self.chamadas)
