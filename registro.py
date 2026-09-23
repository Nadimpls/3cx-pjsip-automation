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
    # Colunas da Fase 2 (batch_id, BINA, eventos SIP, causa de encerramento,
    # durações adicionais) — sempre no final, pra não quebrar a leitura de
    # linhas antigas do CSV (csv.DictReader lê por nome de coluna).
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
    # Colunas da Fase 3 (RTP/codec) — também sempre no final. Só existem
    # pra chamadas atendidas (mídia precisa estar ativa pra medir).
    "codec",
    "payload_type",
    "packets_enviados",
    "packets_recebidos",
    "packet_loss",
    "packet_loss_pct",
    "jitter_medio_ms",
    "jitter_maximo_ms",
    "rtt_ms",
    # Anotações manuais — o sistema não tem como capturar isso sozinho
    # (BINA real e detecção de SPAM exigem visibilidade que só existe no
    # aparelho de destino), então ficam em branco até o usuário preencher
    # depois de encerrar a chamada.
    "bina_manual",
    "spam",
    # Cenário do teste: "ligado" (padrão) ou "desligado" — escolhido na hora
    # de iniciar a bateria, pra poder segmentar histórico/dashboard entre
    # testes com o celular de destino ligado e desligado.
    "cenario",
    # Texto cru da última mensagem SIP recebida da rede (sem parsing nem
    # interpretação) — o "esqueleto" da resposta, pra conferência direta.
    "sip_mensagem_bruta",
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
        # Subtrai o momento do ring menos o momento do invite, dando o valor em segundos
        pdd_s = round(self.t_ring - self.t_invite, 2)

    setup_s = None
    if self.t_invite and self.t_answer:
        setup_s = round(self.t_answer - self.t_invite, 2)

    row = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ramal": self.ramal,
        "tronco": self.operadora,
        "pdd_s": pdd_s,            # PDD em segundos
        "setup_time_s": setup_s,    # Tempo total de atendimento em segundos
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
    """Se o CSV já existir com um cabeçalho mais antigo (menos colunas do
    que o CAMPOS_CSV atual, ex.: antes da Fase 2), reescreve só a linha de
    cabeçalho pra incluir as colunas novas. As linhas de dados antigas não
    são tocadas — csv.DictReader já preenche o que faltar nelas com vazio."""
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
    """Mantém uma lista de chamadas e atualiza a tabela em tempo real."""

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
    """Lê o histórico completo do CSV (todas as execuções, de sempre)."""
    if not os.path.exists(caminho):
        return []
    with open(caminho, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def atualizar_campos_chamada(timestamp, tronco, numero, campos, caminho=CAMINHO_CSV_PADRAO):
    """Atualiza campos preenchidos manualmente (bina_manual, spam) numa
    chamada já registrada, identificada por timestamp+tronco+número (não
    existe um id próprio no CSV, mas essa combinação já é única na prática,
    já que os testes rodam um de cada vez). Reescreve o CSV inteiro,
    preservando as outras linhas como estão.

    Retorna True se achou e atualizou a linha, False se não encontrou."""
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
    """Gera um identificador único pra uma bateria de testes inteira (ex.:
    BATCH-20260916-002), pra depois dar pra comparar operadoras dentro da
    mesma execução. Conta quantos batches já existem hoje no CSV e usa o
    próximo número — chamadas antigas sem batch_id não contam."""
    hoje = time.strftime("%Y%m%d")
    prefixo = f"BATCH-{hoje}-"
    existentes = {
        linha.get("batch_id")
        for linha in ler_todos_resultados(caminho)
        if (linha.get("batch_id") or "").startswith(prefixo)
    }
    return f"{prefixo}{len(existentes) + 1:03d}"


def dias_disponiveis(caminho=CAMINHO_CSV_PADRAO):
    """Retorna as datas (AAAA-MM-DD) com testes registrados, mais recente
    primeiro, junto com a quantidade de testes em cada uma."""
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
    """Todas as linhas do CSV cujo timestamp começa com essa data (AAAA-MM-DD)."""
    return [
        linha for linha in ler_todos_resultados(caminho)
        if (linha.get("timestamp") or "").startswith(data)
    ]


_PADRAO_NOME_AUDIO = re.compile(r"^(.+)_(\d+)_(\d{8})_(\d{6})\.wav$", re.IGNORECASE)


def resultados_do_dia_com_audio(data, audios_dir, caminho=CAMINHO_CSV_PADRAO):
    """Como resultados_do_dia(), mas anexa o nome do arquivo .wav correspondente
    a cada linha atendida (chave "arquivo_audio"), quando existir.

    O CSV não guarda o nome do arquivo de gravação, então o pareamento é feito
    por (operadora, número): agrupamos as gravações daquele dia por essa chave,
    ordenadas pelo horário embutido no próprio nome do arquivo, e casamos em
    ordem com as linhas atendidas daquele mesmo (operadora, número) — como as
    chamadas de uma bateria de testes são sequenciais, a N-ésima gravação de um
    par operadora/número corresponde à N-ésima linha atendida desse par.
    """
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
    """Lista os arquivos .wav gravados numa data (AAAA-MM-DD), mais recentes
    primeiro, a partir da data embutida no próprio nome do arquivo."""
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
    """Converte um valor de célula do CSV pra float, ou None se vazio/
    inválido — nunca inventa um número."""
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _percentil(valores_ordenados, p):
    """Percentil por interpolação linear (método do rank mais próximo com
    interpolação), só com stdlib. `valores_ordenados` já deve estar em
    ordem crescente."""
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
    """Média/mediana/P95/mínimo/máximo de uma lista de números — ou tudo
    None se a lista estiver vazia (métrica sem dado suficiente vira N/D,
    nunca um valor inventado)."""
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
    """Filtro comum das funções de dashboard: por dia (prefixo do timestamp)
    e por cenário (ligado/desligado). Linhas antigas sem "cenario" preenchido
    contam como "ligado" — é o que todo teste era antes desse campo existir."""
    if data:
        linhas = [l for l in linhas if (l.get("timestamp") or "").startswith(data)]
    if cenario:
        linhas = [l for l in linhas if (l.get("cenario") or "ligado") == cenario]
    return linhas


def estatisticas_por_operadora(caminho=CAMINHO_CSV_PADRAO, data=None, cenario=None):
    """Agrega os resultados por operadora (tronco): contagens, ASR, PDD e
    Setup (média/mediana/P95/min/max), ACD (média de talk_duration_s das
    atendidas) e distribuição de códigos SIP. `data` (AAAA-MM-DD) filtra
    pra um dia só; sem ela, agrega tudo. Linhas antigas (de antes das Fases
    2/3) simplesmente não contribuem pros campos que não tinham — a métrica
    fica None se não sobrar dado nenhum, nunca inventada."""
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
    """Uma linha por chamada (não agregado por dia) de uma operadora
    específica, em ordem cronológica — pra ver a variação ligação a
    ligação, não só a média do dia."""
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
    """Como chamadas_por_operadora(), mas com TODAS as operadoras juntas
    numa única linha do tempo cronológica (por chamada, não por dia) — pra
    comparar operadoras chamada a chamada, não só a média do dia."""
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
    """Como estatisticas_por_dia(), mas pra TODAS as operadoras de uma vez,
    agrupadas por dia — pra comparar a tendência de várias operadoras no
    mesmo gráfico em vez de uma por vez."""
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
    """Substituto de PainelAoVivo para uso pela interface web: em vez de
    desenhar uma tabela Rich no terminal, guarda os resultados numa lista
    em memória thread-safe que a API Flask pode ler via /api/results.
    Mesma interface (.registrar(row)) e mesma persistência em CSV."""

    def __init__(self):
        self._lock = threading.Lock()
        self.chamadas = []

    def registrar(self, row):
        salvar_csv(row)
        with self._lock:
            self.chamadas.append(row)

    def adicionar_resultado(self, row):
        """Como .registrar(), mas sem gravar no CSV de novo — usada quando
        quem já gravou o CSV foi o processo isolado do PJSUA2, e aqui só
        precisamos espelhar o resultado em memória para a API servir."""
        with self._lock:
            self.chamadas.append(row)

    def obter_resultados(self):
        with self._lock:
            return list(self.chamadas)