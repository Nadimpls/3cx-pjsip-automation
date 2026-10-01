const OPERADORAS_LABELS = {
    OTIMA: "OTIMA",
    PRIMACOM: "PRIMACOM",
    OKTOR: "OKTOR",
    AGIL: "AGIL",
    EMBRATEL: "EMBRATEL",
    LEMIT: "LEMIT",
};

const CORES_OPERADORAS = ["#3b82f6", "#22c55e", "#eab308", "#ef4444", "#a855f7", "#06b6d4"];

let destinos = [];
let operadorasHabilitadas = [];
let techPorOperadora = {};
let techsDisponiveis = [];
let testeRodando = false;

async function apiGet(caminho) {
    const resp = await fetch(caminho);
    return resp.json();
}

async function apiPost(caminho, corpo) {
    const resp = await fetch(caminho, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo || {}),
    });
    const dados = await resp.json().catch(() => ({}));
    return { ok: resp.ok, dados };
}

function renderDestinos() {
    const lista = document.getElementById("lista-destinos");
    lista.innerHTML = "";
    if (destinos.length === 0) {
        const li = document.createElement("li");
        li.textContent = "Nenhum número adicionado.";
        li.style.color = "var(--texto-fraco)";
        lista.appendChild(li);
        return;
    }
    destinos.forEach((numero, indice) => {
        const li = document.createElement("li");
        const span = document.createElement("span");
        span.textContent = numero;
        const btn = document.createElement("button");
        btn.textContent = "remover";
        btn.onclick = () => {
            destinos.splice(indice, 1);
            renderDestinos();
        };
        li.appendChild(span);
        li.appendChild(btn);
        lista.appendChild(li);
    });
}

function renderOperadoras(disponiveis) {
    const container = document.getElementById("lista-operadoras");
    container.innerHTML = "";
    disponiveis.forEach((op) => {
        const linha = document.createElement("div");
        linha.className = "linha-operadora";

        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = op;
        checkbox.checked = operadorasHabilitadas.includes(op);
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(OPERADORAS_LABELS[op] || op));
        linha.appendChild(label);

        const select = document.createElement("select");
        select.className = "select-tech-operadora";
        select.dataset.operadora = op;
        techsDisponiveis.forEach((tech) => {
            const opt = document.createElement("option");
            opt.value = tech;
            opt.textContent = `Rota ${tech}`;
            select.appendChild(opt);
        });
        select.value = techPorOperadora[op] || techsDisponiveis[0] || "170";
        linha.appendChild(select);

        container.appendChild(linha);
    });
}

function operadorasMarcadas() {
    return Array.from(document.querySelectorAll("#lista-operadoras input[type=checkbox]:checked"))
        .map((el) => el.value);
}

function techPorOperadoraSelecionado() {
    const resultado = {};
    document.querySelectorAll("#lista-operadoras .select-tech-operadora").forEach((select) => {
        resultado[select.dataset.operadora] = select.value;
    });
    return resultado;
}

async function carregarConfig() {
    const [config, disponiveis, techs] = await Promise.all([
        apiGet("/api/config"),
        apiGet("/api/operadoras"),
        apiGet("/api/techs"),
    ]);

    document.getElementById("ramal").value = config.ramal || "";
    document.getElementById("auth_id").value = config.auth_id || "";
    document.getElementById("sip_domain").value = config.sip_domain || "";
    document.getElementById("porta_sip").value = config.porta_sip || 5060;
    document.getElementById("senha").value = "";
    document.getElementById("senha-status").textContent = config.senha_definida
        ? "Senha já definida (deixe em branco para manter)."
        : "Nenhuma senha definida ainda.";

    destinos = config.destinos || [];
    operadorasHabilitadas = config.operadoras_habilitadas || [];
    techPorOperadora = config.tech_por_operadora || {};
    techsDisponiveis = techs || [];

    renderOperadoras(disponiveis);
    renderDestinos();
}

async function salvarConfig(evento) {
    evento.preventDefault();
    const msg = document.getElementById("config-msg");
    msg.textContent = "";

    const corpo = {
        ramal: document.getElementById("ramal").value.trim(),
        auth_id: document.getElementById("auth_id").value.trim(),
        sip_domain: document.getElementById("sip_domain").value.trim(),
        porta_sip: parseInt(document.getElementById("porta_sip").value, 10),
        operadoras_habilitadas: operadorasMarcadas(),
        destinos: destinos,
        tech_por_operadora: techPorOperadoraSelecionado(),
    };

    const senha = document.getElementById("senha").value;
    if (senha) corpo.senha = senha;

    const { ok, dados } = await apiPost("/api/config", corpo);
    if (ok) {
        msg.textContent = "Configuração salva.";
        document.getElementById("senha").value = "";
        document.getElementById("senha-status").textContent = dados.senha_definida
            ? "Senha já definida (deixe em branco para manter)."
            : "Nenhuma senha definida ainda.";
        operadorasHabilitadas = dados.operadoras_habilitadas || [];
        destinos = dados.destinos || [];
        techPorOperadora = dados.tech_por_operadora || {};
        renderDestinos();
    } else {
        msg.textContent = dados.erro || "Erro ao salvar configuração.";
        msg.classList.add("mensagem-erro");
    }
    setTimeout(() => { msg.textContent = ""; }, 4000);
}

function adicionarDestino() {
    const input = document.getElementById("novo-destino");
    const valor = input.value.trim();
    if (!valor) return;
    destinos.push(valor);
    input.value = "";
    renderDestinos();
}

async function iniciarTeste(event) {
    if (event) {
        event.preventDefault(); // Impede o envio via GET/reload do formulário
    }

    document.getElementById("erro-execucao").textContent = "";
    
    const cenarioEscolhido = document.querySelector('input[name="cenario"]:checked');
    const cenario = cenarioEscolhido ? cenarioEscolhido.value : "ligado";

    const { ok, dados } = await apiPost("/api/test/start", { cenario });

    if (!ok) {
        document.getElementById("erro-execucao").textContent = dados.erro || "Não foi possível iniciar.";
    }

    await atualizarStatus();
}

// Vinculação do evento no botão
document.addEventListener("DOMContentLoaded", () => {
    const btnIniciar = document.getElementById("btn-iniciar");
    if (btnIniciar) {
        btnIniciar.addEventListener("click", iniciarTeste);
    }

    const btnParar = document.getElementById("btn-parar");
    if (btnParar) {
        btnParar.addEventListener("click", pararTeste);
    }
});

async function pararTeste() {
    await apiPost("/api/test/stop");
}

function atualizarBotoes() {
    document.getElementById("btn-iniciar").disabled = testeRodando;
    document.getElementById("btn-parar").disabled = !testeRodando;
    const badge = document.getElementById("status-badge");
    badge.textContent = testeRodando ? "Rodando" : "Parado";
    badge.className = "badge " + (testeRodando ? "badge-rodando" : "badge-parado");
}

async function atualizarStatus() {
    const status = await apiGet("/api/test/status");
    testeRodando = status.rodando;
    atualizarBotoes();

    const progresso = document.getElementById("status-progresso");
    document.getElementById("erro-execucao").textContent = status.erro || "";
    if (status.rodando) {
        const partes = [];
        if (status.cenario) partes.push(status.cenario === "desligado" ? "Celular desligado" : "Celular ligado");
        if (status.operadora_atual) partes.push(`Operadora: ${status.operadora_atual}`);
        if (status.numero_atual) partes.push(`Número: ${status.numero_atual}`);
        partes.push(`Concluídos: ${status.testes_concluidos}/${status.total_testes_planejados}`);
        progresso.textContent = partes.join(" · ");
    } else {
        progresso.textContent = status.total_testes_planejados
            ? `Última execução: ${status.testes_concluidos}/${status.total_testes_planejados} testes concluídos.`
            : "";
    }
}

function corSip(codigo) {
    return String(codigo) === "200" ? "sip-ok" : "sip-erro";
}

function ehAtendida(valor) {
    return valor === true || String(valor).toLowerCase() === "true";
}

function corPdd(valor) {
    const n = parseFloat(valor);
    if (isNaN(n)) return "";
    if (n >= 7) return "pdd-critico";
    if (n >= 4) return "pdd-alerta";
    return "";
}

function linhaParaTr(linha) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
        <td>${linha.timestamp ?? ""}</td>
        <td>${linha.ramal ?? ""}</td>
        <td>${linha.tronco ?? ""}</td>
        <td class="${corPdd(linha.pdd_s)}">${linha.pdd_s ?? ""}</td>
        <td>${linha.setup_time_s ?? ""}</td>
        <td class="${corSip(linha.sip_code)}">${linha.sip_code ?? ""}</td>
        <td>${linha.sip_reason ?? ""}</td>
        <td>${ehAtendida(linha.atendida) ? "Sim" : "Não"}</td>
        <td>${linha["Número"] ?? ""}</td>
    `;
    const tdDetalhes = document.createElement("td");
    const btnDetalhes = document.createElement("button");
    btnDetalhes.type = "button";
    btnDetalhes.className = "botao-link";
    btnDetalhes.textContent = "Detalhes";
    btnDetalhes.addEventListener("click", () => abrirModalDetalhes(linha));
    tdDetalhes.appendChild(btnDetalhes);
    tr.appendChild(tdDetalhes);
    return tr;
}

async function atualizarResultados() {
    const linhas = await apiGet("/api/results");
    const tbody = document.querySelector("#tabela-resultados tbody");
    tbody.innerHTML = "";
    linhas.slice().reverse().forEach((linha) => tbody.appendChild(linhaParaTr(linha)));
}

function renderizarListaAudios(lista, arquivos) {
    lista.innerHTML = "";
    if (arquivos.length === 0) {
        const li = document.createElement("li");
        li.textContent = "Nenhuma gravação nesse dia.";
        li.style.color = "var(--texto-fraco)";
        lista.appendChild(li);
        return;
    }
    arquivos.forEach((nome) => {
        const li = document.createElement("li");
        const span = document.createElement("span");
        span.textContent = nome;
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "metadata";
        audio.src = `/api/audios/${encodeURIComponent(nome)}`;
        li.appendChild(span);
        li.appendChild(audio);
        lista.appendChild(li);
    });
}

async function abrirGravacoesDoDia() {
    const data = document.getElementById("select-dia-gravacoes").value;
    if (!data) return;
    const arquivos = await apiGet(`/api/audios/dia/${data}`);
    renderizarListaAudios(document.getElementById("lista-gravacoes-dia"), arquivos);
}

function preencherSelectDias(select, dias) {
    const selecionado = select.value;
    select.innerHTML = "";

    if (dias.length === 0) {
        const option = document.createElement("option");
        option.textContent = "Nenhum teste registrado ainda";
        select.appendChild(option);
        return;
    }

    dias.forEach(({ data, quantidade }) => {
        const option = document.createElement("option");
        option.value = data;
        option.textContent = `${data} (${quantidade} teste${quantidade === 1 ? "" : "s"})`;
        select.appendChild(option);
    });

    if (selecionado && dias.some((d) => d.data === selecionado)) {
        select.value = selecionado;
    }
}

function preencherSelectDiasComTodos(select, dias) {
    const selecionado = select.value;
    select.innerHTML = "";

    const optTodos = document.createElement("option");
    optTodos.value = "";
    optTodos.textContent = "Todos os dias";
    select.appendChild(optTodos);

    dias.forEach(({ data, quantidade }) => {
        const option = document.createElement("option");
        option.value = data;
        option.textContent = `${data} (${quantidade} teste${quantidade === 1 ? "" : "s"})`;
        select.appendChild(option);
    });

    select.value = selecionado || "";
}

async function carregarDias() {
    const dias = await apiGet("/api/historico/dias");
    preencherSelectDias(document.getElementById("select-dia"), dias);
    preencherSelectDias(document.getElementById("select-dia-gravacoes"), dias);
    preencherSelectDiasComTodos(document.getElementById("select-dia-dashboard"), dias);
}

function formatoStatCurto(stat) {
    if (!stat || stat.media === null || stat.media === undefined) return "N/D";
    return `${stat.media}s / ${stat.mediana}s / ${stat.p95}s`;
}

function escalaPontosX(n, margemEsquerda, larguraUtil) {
    if (n <= 1) return [margemEsquerda + larguraUtil / 2];
    const passo = larguraUtil / (n - 1);
    return Array.from({ length: n }, (_, i) => margemEsquerda + i * passo);
}

function segmentosContinuos(pontos) {
    // Agrupa em polylines separadas onde houver "buraco" (valor ausente),
    // pra não desenhar uma linha reta por cima de um dia sem dado.
    const segmentos = [];
    let atual = [];
    pontos.forEach((p) => {
        if (p === null) {
            if (atual.length > 1) segmentos.push(atual);
            atual = [];
        } else {
            atual.push(p);
        }
    });
    if (atual.length > 1) segmentos.push(atual);
    return segmentos;
}

function formatarRotuloEixo(valor) {
    const arredondado = Math.round(valor * 100) / 100;
    return String(arredondado);
}

function desenharGradeY(maximo, largura, altura, margemEsquerda, margemDireita, margemBaixo, margemTopo, numLinhas) {
    numLinhas = numLinhas || 5;
    const alturaUtil = altura - margemBaixo - margemTopo;
    let svg = "";
    for (let i = 0; i <= numLinhas; i++) {
        const valor = (maximo / numLinhas) * i;
        const y = altura - margemBaixo - (valor / maximo) * alturaUtil;
        svg += `<line x1="${margemEsquerda}" y1="${y}" x2="${largura - margemDireita}" y2="${y}" class="grafico-grade" />`;
        svg += `<text x="${margemEsquerda - 8}" y="${y + 4}" text-anchor="end" class="grafico-rotulo-y">${formatarRotuloEixo(valor)}</text>`;
    }
    return svg;
}

function graficoLinha(itens, obterValor, obterRotulo, sufixo) {
    sufixo = sufixo || "";
    const largura = 700;
    const altura = 280;
    const margemBaixo = 50;
    const margemEsquerda = 40;
    const margemDireita = 24;
    const margemTopo = 20;
    const larguraUtil = largura - margemEsquerda - margemDireita;
    const alturaUtil = altura - margemBaixo - margemTopo;

    if (!itens || itens.length === 0) {
        return `<p class="dica">Sem dados suficientes.</p>`;
    }

    const validos = itens.map(obterValor).filter((v) => v !== null && v !== undefined && !isNaN(v));
    const maximo = validos.length ? Math.max(...validos, 0.0001) : 1;
    const xs = escalaPontosX(itens.length, margemEsquerda, larguraUtil);

    let svg = `<svg viewBox="0 0 ${largura} ${altura}" class="grafico-svg">`;
    svg += desenharGradeY(maximo, largura, altura, margemEsquerda, margemDireita, margemBaixo, margemTopo);
    svg += `<line x1="${margemEsquerda}" y1="${altura - margemBaixo}" x2="${largura - margemDireita}" y2="${altura - margemBaixo}" stroke="var(--borda)" />`;

    const pontos = itens.map((item, i) => {
        const v = obterValor(item);
        if (v === null || v === undefined || isNaN(v)) return null;
        return `${xs[i]},${altura - margemBaixo - (v / maximo) * alturaUtil}`;
    });
    segmentosContinuos(pontos).forEach((seg) => {
        svg += `<polyline points="${seg.join(" ")}" fill="none" stroke="var(--primaria)" stroke-width="2" />`;
    });

    // Com muitos pontos (ex.: dezenas de ligações), mostrar rótulo em todo
    // mundo lota o eixo — mostra só um a cada N pra continuar legível.
    const passoRotulo = Math.max(1, Math.ceil(itens.length / 12));

    itens.forEach((item, i) => {
        const v = obterValor(item);
        if (i % passoRotulo === 0 || i === itens.length - 1) {
            svg += `<text x="${xs[i]}" y="${altura - margemBaixo + 16}" text-anchor="middle" class="grafico-rotulo">${obterRotulo(item)}</text>`;
        }
        if (v !== null && v !== undefined && !isNaN(v)) {
            const y = altura - margemBaixo - (v / maximo) * alturaUtil;
            svg += `<circle cx="${xs[i]}" cy="${y}" r="3.5" fill="var(--primaria)"><title>${obterRotulo(item)}: ${v}${sufixo}</title></circle>`;
        }
    });

    svg += `</svg>`;
    return svg;
}

function graficoLinhasMultiplas(dias, operadorasChave, metrica, sufixo) {
    sufixo = sufixo || "";
    const largura = 700;
    const altura = 280;
    const margemBaixo = 50;
    const margemEsquerda = 40;
    const margemDireita = 24;
    const margemTopo = 20;
    const larguraUtil = largura - margemEsquerda - margemDireita;
    const alturaUtil = altura - margemBaixo - margemTopo;

    if (!dias || dias.length === 0 || operadorasChave.length === 0) {
        return `<p class="dica">Sem dados suficientes.</p>`;
    }

    let maximo = 0;
    dias.forEach((dia) => {
        operadorasChave.forEach((op) => {
            const v = dia.operadoras[op] ? dia.operadoras[op][metrica] : null;
            if (v !== null && v !== undefined && v > maximo) maximo = v;
        });
    });
    maximo = maximo || 1;

    const xs = escalaPontosX(dias.length, margemEsquerda, larguraUtil);

    let svg = `<svg viewBox="0 0 ${largura} ${altura}" class="grafico-svg">`;
    svg += desenharGradeY(maximo, largura, altura, margemEsquerda, margemDireita, margemBaixo, margemTopo);
    svg += `<line x1="${margemEsquerda}" y1="${altura - margemBaixo}" x2="${largura - margemDireita}" y2="${altura - margemBaixo}" stroke="var(--borda)" />`;

    operadorasChave.forEach((op, indiceOp) => {
        const cor = CORES_OPERADORAS[indiceOp % CORES_OPERADORAS.length];
        const pontosCirculo = [];
        const pontos = dias.map((dia, i) => {
            const v = dia.operadoras[op] ? dia.operadoras[op][metrica] : null;
            if (v === null || v === undefined) return null;
            const y = altura - margemBaixo - (v / maximo) * alturaUtil;
            pontosCirculo.push({ x: xs[i], y, v });
            return `${xs[i]},${y}`;
        });
        segmentosContinuos(pontos).forEach((seg) => {
            svg += `<polyline points="${seg.join(" ")}" fill="none" stroke="${cor}" stroke-width="2" />`;
        });
        pontosCirculo.forEach((p) => {
            svg += `<circle cx="${p.x}" cy="${p.y}" r="3" fill="${cor}"><title>${OPERADORAS_LABELS[op] || op}: ${p.v}${sufixo}</title></circle>`;
        });
    });

    dias.forEach((dia, i) => {
        svg += `<text x="${xs[i]}" y="${altura - margemBaixo + 16}" text-anchor="middle" class="grafico-rotulo">${dia.data.slice(5)}</text>`;
    });

    svg += `</svg>`;
    return svg;
}

function graficoLinhasMultiplasPorLigacao(chamadas, operadorasChave, metrica, sufixo) {
    // chamadas: todas as operadoras juntas, já em ordem cronológica — o
    // eixo X é a posição de cada chamada nessa linha do tempo compartilhada,
    // e cada operadora só tem ponto nas posições onde ela teve chamada
    // (resto fica em branco, sem interpolar por cima).
    sufixo = sufixo || "";
    const largura = 700;
    const altura = 280;
    const margemBaixo = 50;
    const margemEsquerda = 40;
    const margemDireita = 24;
    const margemTopo = 20;
    const larguraUtil = largura - margemEsquerda - margemDireita;
    const alturaUtil = altura - margemBaixo - margemTopo;

    if (!chamadas || chamadas.length === 0 || operadorasChave.length === 0) {
        return `<p class="dica">Sem dados suficientes.</p>`;
    }

    let maximo = 0;
    chamadas.forEach((c) => {
        const v = c[metrica];
        if (v !== null && v !== undefined && v > maximo) maximo = v;
    });
    maximo = maximo || 1;

    const xs = escalaPontosX(chamadas.length, margemEsquerda, larguraUtil);

    let svg = `<svg viewBox="0 0 ${largura} ${altura}" class="grafico-svg">`;
    svg += desenharGradeY(maximo, largura, altura, margemEsquerda, margemDireita, margemBaixo, margemTopo);
    svg += `<line x1="${margemEsquerda}" y1="${altura - margemBaixo}" x2="${largura - margemDireita}" y2="${altura - margemBaixo}" stroke="var(--borda)" />`;

    operadorasChave.forEach((op, indiceOp) => {
        const cor = CORES_OPERADORAS[indiceOp % CORES_OPERADORAS.length];
        const pontosCirculo = [];
        const pontos = chamadas.map((c, i) => {
            if (c.tronco !== op) return null;
            const v = c[metrica];
            if (v === null || v === undefined) return null;
            const y = altura - margemBaixo - (v / maximo) * alturaUtil;
            pontosCirculo.push({ x: xs[i], y, v });
            return `${xs[i]},${y}`;
        });
        segmentosContinuos(pontos).forEach((seg) => {
            svg += `<polyline points="${seg.join(" ")}" fill="none" stroke="${cor}" stroke-width="2" />`;
        });
        pontosCirculo.forEach((p) => {
            svg += `<circle cx="${p.x}" cy="${p.y}" r="3" fill="${cor}"><title>${OPERADORAS_LABELS[op] || op}: ${p.v}${sufixo}</title></circle>`;
        });
    });

    const passoRotulo = Math.max(1, Math.ceil(chamadas.length / 12));
    chamadas.forEach((c, i) => {
        if (i % passoRotulo === 0 || i === chamadas.length - 1) {
            const rotulo = c.timestamp ? c.timestamp.slice(11, 16) : "?";
            svg += `<text x="${xs[i]}" y="${altura - margemBaixo + 16}" text-anchor="middle" class="grafico-rotulo">${rotulo}</text>`;
        }
    });

    svg += `</svg>`;
    return svg;
}

function renderizarLegendaOperadoras(elementoId, operadoras) {
    document.getElementById(elementoId).innerHTML = operadoras.map((op, i) => `
        <span class="legenda-item">
            <span class="legenda-cor" style="background:${CORES_OPERADORAS[i % CORES_OPERADORAS.length]}"></span>
            ${OPERADORAS_LABELS[op] || op}
        </span>
    `).join("");
}

function graficoBarras(itens, obterValor, obterRotulo, sufixo) {
    sufixo = sufixo || "";
    const largura = 480;
    const alturaBarra = 22;
    const espacamento = 10;
    const margemEsquerda = 90;
    const margemDireita = 55;

    if (!itens || itens.length === 0) {
        return `<p class="dica">Sem dados suficientes.</p>`;
    }

    const altura = itens.length * (alturaBarra + espacamento) + espacamento;
    const valores = itens.map(obterValor).filter((v) => v !== null && v !== undefined && !isNaN(v));
    const maximo = valores.length ? Math.max(...valores, 0.0001) : 1;
    const larguraUtil = largura - margemEsquerda - margemDireita;

    let svg = `<svg viewBox="0 0 ${largura} ${altura}" class="grafico-svg">`;
    itens.forEach((item, i) => {
        const valor = obterValor(item);
        const y = espacamento + i * (alturaBarra + espacamento);
        const rotulo = obterRotulo(item);
        svg += `<text x="0" y="${y + alturaBarra / 2 + 4}" class="grafico-rotulo">${rotulo}</text>`;
        if (valor !== null && valor !== undefined && !isNaN(valor)) {
            const larguraBarra = Math.max((valor / maximo) * larguraUtil, 1);
            svg += `<rect x="${margemEsquerda}" y="${y}" width="${larguraBarra}" height="${alturaBarra}" rx="3" class="grafico-barra" />`;
            svg += `<text x="${margemEsquerda + larguraBarra + 6}" y="${y + alturaBarra / 2 + 4}" class="grafico-valor">${valor}${sufixo}</text>`;
        } else {
            svg += `<text x="${margemEsquerda}" y="${y + alturaBarra / 2 + 4}" class="grafico-valor">N/D</text>`;
        }
    });
    svg += `</svg>`;
    return svg;
}

function cartaoOperadora(item) {
    const div = document.createElement("div");
    div.className = "cartao-operadora";

    const distribuicaoTexto = Object.entries(item.distribuicao_sip || {})
        .map(([codigo, qtd]) => `${codigo}: ${qtd}`)
        .join(" · ") || "N/D";

    div.innerHTML = `
        <h3>${OPERADORAS_LABELS[item.operadora] || item.operadora}</h3>
        <div class="linha-metrica"><span>Testes</span><span>${item.total_testes}</span></div>
        <div class="linha-metrica"><span>Atendidas / não atendidas</span><span>${item.atendidas} / ${item.nao_atendidas}</span></div>
        <div class="linha-metrica"><span>ASR</span><span>${item.asr_pct ?? "N/D"}${item.asr_pct !== null ? "%" : ""}</span></div>
        <div class="linha-metrica"><span>ACD</span><span>${item.acd_s ?? "N/D"}${item.acd_s !== null ? "s" : ""}</span></div>
        <div class="subtitulo-metricas">PDD (média / mediana / P95)</div>
        <div class="linha-metrica"><span>&nbsp;</span><span>${formatoStatCurto(item.pdd)}</span></div>
        <div class="subtitulo-metricas">Setup (média / mediana / P95)</div>
        <div class="linha-metrica"><span>&nbsp;</span><span>${formatoStatCurto(item.setup)}</span></div>
        <div class="subtitulo-metricas">Códigos SIP</div>
        <div class="linha-metrica"><span>${distribuicaoTexto}</span><span></span></div>
    `;
    return div;
}

function rotuloOperadora(item) {
    return OPERADORAS_LABELS[item.operadora] || item.operadora;
}

function parametroCenarioDashboard() {
    const cenario = document.getElementById("select-cenario-dashboard").value;
    return cenario ? `cenario=${encodeURIComponent(cenario)}` : "";
}

function montarQuery(...partes) {
    const validas = partes.filter(Boolean);
    return validas.length ? `?${validas.join("&")}` : "";
}

async function carregarDashboard() {
    const data = document.getElementById("select-dia-dashboard").value;
    const query = montarQuery(data ? `data=${encodeURIComponent(data)}` : "", parametroCenarioDashboard());
    const itens = await apiGet(`/api/dashboard${query}`);

    const container = document.getElementById("cartoes-dashboard");
    container.innerHTML = "";
    if (itens.length === 0) {
        container.textContent = "Nenhum teste registrado ainda.";
        document.getElementById("grafico-asr").innerHTML = "";
        document.getElementById("grafico-pdd").innerHTML = "";
        document.getElementById("grafico-setup").innerHTML = "";
        return;
    }
    itens.forEach((item) => container.appendChild(cartaoOperadora(item)));

    document.getElementById("grafico-asr").innerHTML =
        graficoBarras(itens, (i) => i.asr_pct, rotuloOperadora, "%");
    document.getElementById("grafico-pdd").innerHTML =
        graficoBarras(itens, (i) => (i.pdd ? i.pdd.media : null), rotuloOperadora, "s");
    document.getElementById("grafico-setup").innerHTML =
        graficoBarras(itens, (i) => (i.setup ? i.setup.media : null), rotuloOperadora, "s");
}

async function preencherSelectOperadoraEvolucao() {
    const disponiveis = await apiGet("/api/operadoras");
    const select = document.getElementById("select-operadora-evolucao");
    disponiveis.forEach((op) => {
        const option = document.createElement("option");
        option.value = op;
        option.textContent = OPERADORAS_LABELS[op] || op;
        select.appendChild(option);
    });
}

const METRICAS_EVOLUCAO_POR_DIA = [
    { valor: "asr_pct", rotulo: "ASR (%)" },
    { valor: "pdd_medio", rotulo: "PDD médio (s)" },
    { valor: "setup_medio", rotulo: "Setup médio (s)" },
];

const METRICAS_EVOLUCAO_POR_LIGACAO = [
    { valor: "pdd_s", rotulo: "PDD (s)" },
    { valor: "setup_time_s", rotulo: "Setup (s)" },
];

function atualizarOpcoesMetricaEvolucao() {
    const agrupamento = document.getElementById("select-agrupamento-evolucao").value;
    const select = document.getElementById("select-metrica-evolucao");
    const selecionada = select.value;
    const opcoes = agrupamento === "ligacao" ? METRICAS_EVOLUCAO_POR_LIGACAO : METRICAS_EVOLUCAO_POR_DIA;

    select.innerHTML = "";
    opcoes.forEach(({ valor, rotulo }) => {
        const option = document.createElement("option");
        option.value = valor;
        option.textContent = rotulo;
        select.appendChild(option);
    });

    if (opcoes.some((o) => o.valor === selecionada)) {
        select.value = selecionada;
    }
}

async function carregarEvolucao() {
    const operadora = document.getElementById("select-operadora-evolucao").value;
    const agrupamento = document.getElementById("select-agrupamento-evolucao").value;
    const metrica = document.getElementById("select-metrica-evolucao").value;
    const alvo = document.getElementById("grafico-evolucao");
    if (!operadora) {
        alvo.innerHTML = "";
        return;
    }

    const paramOperadora = `operadora=${encodeURIComponent(operadora)}`;
    const paramCenario = parametroCenarioDashboard();

    if (agrupamento === "ligacao") {
        const chamadas = await apiGet(`/api/dashboard/chamadas${montarQuery(paramOperadora, paramCenario)}`);
        const rotuloChamada = (c) => (c.timestamp ? c.timestamp.slice(11, 16) : "?");
        alvo.innerHTML = graficoLinha(chamadas, (c) => c[metrica], rotuloChamada, "s");
        return;
    }

    const dias = await apiGet(`/api/dashboard/evolucao${montarQuery(paramOperadora, paramCenario)}`);
    const sufixo = metrica === "asr_pct" ? "%" : "s";
    alvo.innerHTML = graficoLinha(dias, (d) => d[metrica], (d) => d.data.slice(5), sufixo);
}

function atualizarOpcoesMetricaComparacao() {
    const agrupamento = document.getElementById("select-agrupamento-comparacao").value;
    const select = document.getElementById("select-metrica-comparacao");
    const selecionada = select.value;
    const opcoes = agrupamento === "ligacao" ? METRICAS_EVOLUCAO_POR_LIGACAO : METRICAS_EVOLUCAO_POR_DIA;

    select.innerHTML = "";
    opcoes.forEach(({ valor, rotulo }) => {
        const option = document.createElement("option");
        option.value = valor;
        option.textContent = rotulo;
        select.appendChild(option);
    });

    if (opcoes.some((o) => o.valor === selecionada)) {
        select.value = selecionada;
    }
}

async function carregarComparacaoTempo() {
    const agrupamento = document.getElementById("select-agrupamento-comparacao").value;
    const metrica = document.getElementById("select-metrica-comparacao").value;
    const paramCenario = parametroCenarioDashboard();

    if (agrupamento === "ligacao") {
        const [chamadas, operadoras] = await Promise.all([
            apiGet(`/api/dashboard/chamadas-todas${montarQuery(paramCenario)}`),
            apiGet("/api/operadoras"),
        ]);
        document.getElementById("grafico-comparacao-tempo").innerHTML =
            graficoLinhasMultiplasPorLigacao(chamadas, operadoras, metrica, "s");
        renderizarLegendaOperadoras("legenda-comparacao-tempo", operadoras);
        return;
    }

    const [dias, operadoras] = await Promise.all([
        apiGet(`/api/dashboard/evolucao-todas${montarQuery(paramCenario)}`),
        apiGet("/api/operadoras"),
    ]);
    const sufixo = metrica === "asr_pct" ? "%" : "s";
    document.getElementById("grafico-comparacao-tempo").innerHTML =
        graficoLinhasMultiplas(dias, operadoras, metrica, sufixo);
    renderizarLegendaOperadoras("legenda-comparacao-tempo", operadoras);
}

function linhaHistoricoParaTr(linha) {
    const tr = linhaParaTr(linha);

    const tdRota = document.createElement("td");
    tdRota.textContent = linha.rota || "—";
    if (!linha.rota) tdRota.style.color = "var(--texto-fraco)";
    tr.insertBefore(tdRota, tr.children[3]);

    const tdBina = document.createElement("td");
    tdBina.textContent = linha.bina_manual || "—";
    if (!linha.bina_manual) tdBina.style.color = "var(--texto-fraco)";
    tr.insertBefore(tdBina, tr.lastElementChild);

    const tdSpam = document.createElement("td");
    if (linha.spam === "sim") {
        tdSpam.textContent = "Sim";
        tdSpam.classList.add("sip-erro");
    } else if (linha.spam === "nao") {
        tdSpam.textContent = "Não";
    } else {
        tdSpam.textContent = "—";
        tdSpam.style.color = "var(--texto-fraco)";
    }
    tr.insertBefore(tdSpam, tr.lastElementChild);

    const tdAudio = document.createElement("td");
    if (linha.arquivo_audio) {
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "metadata";
        audio.src = `/api/audios/${encodeURIComponent(linha.arquivo_audio)}`;
        tdAudio.appendChild(audio);
    } else {
        tdAudio.textContent = "—";
        tdAudio.style.color = "var(--texto-fraco)";
    }
    tr.insertBefore(tdAudio, tr.lastElementChild);
    return tr;
}

let linhasHistoricoAtual = [];

function renderizarHistoricoFiltrado() {
    const operadora = document.getElementById("filtro-operadora").value;
    const destino = document.getElementById("filtro-destino").value.trim();
    const atendidaFiltro = document.getElementById("filtro-atendida").value;
    const cenarioFiltro = document.getElementById("filtro-cenario").value;

    const filtradas = linhasHistoricoAtual.filter((linha) => {
        if (operadora && linha.tronco !== operadora) return false;
        if (destino && !String(linha["Número"] ?? "").includes(destino)) return false;
        if (atendidaFiltro === "sim" && !ehAtendida(linha.atendida)) return false;
        if (atendidaFiltro === "nao" && ehAtendida(linha.atendida)) return false;
        if (cenarioFiltro && (linha.cenario || "ligado") !== cenarioFiltro) return false;
        return true;
    });

    const tbody = document.querySelector("#tabela-historico tbody");
    tbody.innerHTML = "";
    filtradas.forEach((linha) => tbody.appendChild(linhaHistoricoParaTr(linha)));
}

async function preencherFiltroOperadoras() {
    const disponiveis = await apiGet("/api/operadoras");
    const select = document.getElementById("filtro-operadora");
    disponiveis.forEach((op) => {
        const option = document.createElement("option");
        option.value = op;
        option.textContent = OPERADORAS_LABELS[op] || op;
        select.appendChild(option);
    });
}

function valorOuND(v) {
    if (v === null || v === undefined || v === "") return "N/D";
    return v;
}

function campoDetalhe(rotulo, valor) {
    const div = document.createElement("div");
    div.className = "campo-detalhe";
    div.innerHTML = `<span class="rotulo">${rotulo}</span>${valorOuND(valor)}`;
    return div;
}

function preencherCampos(containerId, pares) {
    const container = document.getElementById(containerId);
    container.innerHTML = "";
    pares.forEach(([rotulo, valor]) => container.appendChild(campoDetalhe(rotulo, valor)));
}

let linhaAtualModal = null;

function abrirModalDetalhes(linha) {
    linhaAtualModal = linha;

    preencherCampos("detalhes-identificacao", [
        ["Operadora", linha.tronco],
        ["Ramal", linha.ramal],
        ["BINA configurado", linha.bina_configurado],
        ["BINA enviado", linha.bina_enviado],
        ["From enviado", linha.bina_header_from],
        ["P-Asserted-Identity", linha.bina_header_pai],
        ["Remote-Party-ID", linha.bina_header_rpid],
        ["Destino", linha["Número"]],
        ["Horário", linha.timestamp],
        ["Batch ID", linha.batch_id],
        ["Cenário", linha.cenario === "desligado" ? "Celular desligado" : "Celular ligado"],
    ]);

    document.getElementById("input-bina-manual").value = linha.bina_manual || "";
    document.getElementById("select-spam-manual").value = linha.spam || "";
    document.getElementById("msg-anotacoes").textContent = "";

    preencherCampos("detalhes-tempos", [
        ["PDD (s)", linha.pdd_s],
        ["Setup (s)", linha.setup_time_s],
        ["Ring duration (s)", linha.ring_duration_s],
        ["Talk duration (s)", linha.talk_duration_s],
        ["Total duration (s)", linha.total_duration_s],
    ]);

    preencherCampos("detalhes-sinalizacao", [
        ["Código SIP", linha.sip_code],
        ["Motivo SIP", linha.sip_reason],
        ["Q.850", linha.q850_cause],
        ["Release by", linha.release_by ? `${linha.release_by} (${linha.release_by_fonte || "inferido"})` : null],
        ["Atendida", ehAtendida(linha.atendida) ? "Sim" : "Não"],
    ]);

    const listaEventos = document.getElementById("detalhes-eventos-sip");
    listaEventos.innerHTML = "";
    let eventos = [];
    try {
        eventos = linha.sip_events ? JSON.parse(linha.sip_events) : [];
    } catch (erro) {
        eventos = [];
    }
    if (!eventos || eventos.length === 0) {
        const li = document.createElement("li");
        li.textContent = "Nenhum evento SIP registrado.";
        li.style.color = "var(--texto-fraco)";
        listaEventos.appendChild(li);
    } else {
        eventos.forEach((ev) => {
            const li = document.createElement("li");
            const tempo = ev.t_desde_invite_s !== null && ev.t_desde_invite_s !== undefined ? `+${ev.t_desde_invite_s}s` : "?";
            li.textContent = `${tempo} — ${ev.codigo ?? ""} ${ev.motivo ?? ""}`;
            listaEventos.appendChild(li);
        });
    }

    document.getElementById("detalhes-sip-bruto").textContent =
        linha.sip_mensagem_bruta || "Nenhuma mensagem SIP bruta capturada pra esta chamada.";

    preencherCampos("detalhes-midia", [
        ["Codec", linha.codec],
        ["Payload type", linha.payload_type],
        ["Pacotes enviados", linha.packets_enviados],
        ["Pacotes recebidos", linha.packets_recebidos],
        ["Packet loss", linha.packet_loss],
        ["Packet loss (%)", linha.packet_loss_pct],
        ["Jitter médio (ms)", linha.jitter_medio_ms],
        ["Jitter máximo (ms)", linha.jitter_maximo_ms],
        ["RTT (ms)", linha.rtt_ms],
    ]);

    const divGravacao = document.getElementById("detalhes-gravacao");
    divGravacao.innerHTML = "";
    if (linha.arquivo_audio) {
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "metadata";
        audio.src = `/api/audios/${encodeURIComponent(linha.arquivo_audio)}`;
        divGravacao.appendChild(audio);

        const link = document.createElement("a");
        link.href = audio.src;
        link.textContent = "Baixar gravação";
        link.download = linha.arquivo_audio;
        link.className = "botao-link";
        link.style.marginLeft = "12px";
        divGravacao.appendChild(link);
    } else {
        divGravacao.textContent = "Não disponível nesta visão — consulte o Histórico.";
        divGravacao.style.color = "var(--texto-fraco)";
    }

    document.getElementById("modal-detalhes").style.display = "flex";
}

function fecharModal() {
    document.getElementById("modal-detalhes").style.display = "none";
}

async function salvarAnotacoes() {
    if (!linhaAtualModal) return;

    const bina_manual = document.getElementById("input-bina-manual").value.trim();
    const spam = document.getElementById("select-spam-manual").value;
    const msg = document.getElementById("msg-anotacoes");

    const { ok, dados } = await apiPost("/api/historico/atualizar", {
        timestamp: linhaAtualModal.timestamp,
        tronco: linhaAtualModal.tronco,
        numero: linhaAtualModal["Número"],
        bina_manual,
        spam,
    });

    if (ok) {
        linhaAtualModal.bina_manual = bina_manual;
        linhaAtualModal.spam = spam;
        msg.textContent = "Salvo.";
        msg.classList.remove("mensagem-erro");
        renderizarHistoricoFiltrado();
    } else {
        msg.textContent = dados.erro || "Erro ao salvar.";
        msg.classList.add("mensagem-erro");
    }
    setTimeout(() => { msg.textContent = ""; }, 4000);
}

async function abrirDiaHistorico() {
    const data = document.getElementById("select-dia").value;
    if (!data) return;

    linhasHistoricoAtual = await apiGet(`/api/historico/${data}`);
    renderizarHistoricoFiltrado();

    const link = document.getElementById("link-baixar-csv");
    link.href = `/api/historico/${data}/csv`;
    link.style.display = "inline-block";
}

function iniciarPolling() {
    setInterval(atualizarStatus, 1500);
    setInterval(atualizarResultados, 2000);
    setInterval(carregarDias, 10000);
}

function trocarView(nomeView) {
    document.querySelectorAll(".nav-item").forEach((btn) => {
        btn.classList.toggle("ativo", btn.dataset.view === nomeView);
    });
    ["painel", "gravacoes", "historico", "dashboard", "sobre"].forEach((view) => {
        document.getElementById(`view-${view}`).style.display = view === nomeView ? "grid" : "none";
    });
    if (nomeView === "dashboard") {
        carregarDashboard();
        carregarEvolucao();
        carregarComparacaoTempo();
    }
}

document.getElementById("form-config").addEventListener("submit", salvarConfig);
document.getElementById("btn-add-destino").addEventListener("click", adicionarDestino);
document.getElementById("novo-destino").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); adicionarDestino(); }
});
document.getElementById("btn-iniciar").addEventListener("click", iniciarTeste);
document.getElementById("btn-parar").addEventListener("click", pararTeste);
document.getElementById("btn-abrir-dia").addEventListener("click", abrirDiaHistorico);
document.getElementById("btn-ver-gravacoes").addEventListener("click", abrirGravacoesDoDia);
document.getElementById("btn-atualizar-dashboard").addEventListener("click", carregarDashboard);
document.getElementById("select-operadora-evolucao").addEventListener("change", carregarEvolucao);
document.getElementById("select-metrica-evolucao").addEventListener("change", carregarEvolucao);
document.getElementById("select-agrupamento-evolucao").addEventListener("change", () => {
    atualizarOpcoesMetricaEvolucao();
    carregarEvolucao();
});
document.getElementById("select-metrica-comparacao").addEventListener("change", carregarComparacaoTempo);
document.getElementById("select-agrupamento-comparacao").addEventListener("change", () => {
    atualizarOpcoesMetricaComparacao();
    carregarComparacaoTempo();
});
document.getElementById("select-cenario-dashboard").addEventListener("change", () => {
    carregarDashboard();
    carregarEvolucao();
    carregarComparacaoTempo();
});
document.getElementById("btn-fechar-modal").addEventListener("click", fecharModal);
document.getElementById("btn-salvar-anotacoes").addEventListener("click", salvarAnotacoes);
document.getElementById("modal-detalhes").addEventListener("click", (ev) => {
    if (ev.target.id === "modal-detalhes") fecharModal();
});
["filtro-operadora", "filtro-atendida", "filtro-cenario"].forEach((id) => {
    document.getElementById(id).addEventListener("change", renderizarHistoricoFiltrado);
});
document.getElementById("filtro-destino").addEventListener("input", renderizarHistoricoFiltrado);
document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => trocarView(btn.dataset.view));
});

carregarConfig();
carregarDias();
preencherFiltroOperadoras();
preencherSelectOperadoraEvolucao();
atualizarOpcoesMetricaEvolucao();
atualizarOpcoesMetricaComparacao();
atualizarStatus();
atualizarResultados();
iniciarPolling();
