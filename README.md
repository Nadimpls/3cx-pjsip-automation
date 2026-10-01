# 📞 Automação de Testes de Telefonia SIP (3CX & PJSIP)

Sistema de automação em Python para disparo e monitoramento de baterias de testes SIP, validação de rotas telefônicas, medição de métricas operacionais (PDD, Status SIP e causas Q.850) e gravação de chamadas, integrado ao 3CX/Asterisk via bindings PJSIP (pjSUA2) e com Dashboard Web em Flask.

## ⚙️ Funcionalidades

- **Medição de PDD (Post Dial Delay):** Captura do tempo em milissegundos entre o `INVITE` e a resposta da rede (`180`/`183`/`200`).
- **Análise de Status SIP & Q.850:** Mapeamento e validação do código de terminação de cada chamada.
- **Gravação Automática de Mídia:** Captura e armazenamento de arquivos `.wav` de chamadas atendidas através do módulo `gravador.py`.
- **Baterias de Testes Configuráveis:** Suítes dedicadas para testes de sensibilidade (`rate_sensitivity.py`), resiliência e reconexão (`reattach.py`).
- **Persistência em SQLite:** Histórico gravado localmente na tabela `chamadas` do banco `telecom.db`.
- **Dashboard Web / Interface de Gestão:** Servidor Flask para visualização e controle de métricas do sistema.
- **Gerenciamento de Credenciais Cifradas:** Uso da biblioteca `cryptography` (Fernet) via `secret.key` para proteger dados de acesso SIP.

## 🛠️ Tecnologias Utilizadas

- **Linguagem:** Python 3.x
- **SIP Engine:** PJSIP / PJSUA2 (bindings em C++)
- **Backend Web:** Flask (`app.py`)
- **Criptografia:** `cryptography.fernet`
- **Banco de Dados:** SQLite3 (`telecom.db`)
- **Ambiente de Desenvolvimento:** MSYS2 / MinGW64 / VS Code

## 📂 Estrutura do Repositório

```text
.
├── baterias/               # Suítes de testes automatizados (core, sensibilidade e reattach)
│   ├── __init__.py
│   ├── core.py
│   ├── rate_sensitivity.py
│   └── reattach.py
├── pjsua2_backup/          # Binários e backups do binding PJSIP/PJSUA2
├── static/                 # Arquivos estáticos do painel Web (CSS, JS)
│   ├── app.js
│   ├── app.zip
│   └── style.css
├── templates/              # Templates HTML renderizados pelo Flask
│   └── index.html
├── .gitignore              # Regras de exclusão do Git
├── app.py                  # Servidor Web / API Flask
├── config_manager.py       # Gerenciador de configurações e descriptografia de credenciais
├── config.example.json     # Modelo limpo de configuração para a aplicação
├── config.json             # Configurações locais (ignoradas no Git)
├── db.py                   # Criação e manipulação do banco SQLite (telecom.db)
├── gravador.py             # Módulo de gravação de áudio das chamadas
├── main.py                 # Orquestrador do PJSIP e disparo de chamadas
├── pjsip_worker.py         # Worker para gerenciamento de eventos e sessões SIP
├── pjsua2.py               # Wrapper Python da biblioteca PJSIP
├── README.md               # Documentação do projeto
├── registro.py             # Módulo de registro de troncos/ramais SIP
├── requirements-web.txt    # Dependências de bibliotecas Python
├── secret.key              # Chave local de criptografia (ignorada no Git)
├── telecom.db              # Banco de dados SQLite local (ignorado no Git)
└── ver_banco.py            # Script utilitário para leitura de chamadas gravadas
```

## 🚀 Como Executar

### 1. Pré-requisitos

- Python 3.x instalado (ambiente MSYS2/MinGW64 ou similar).
- Biblioteca nativa PJSIP (`pjsua2`) compilada no diretório da aplicação (`pjsua2.py` e arquivos nativos correspondentes).

### 2. Instalação das dependências

```bash
pip install -r requirements-web.txt
```

### 3. Configuração do ambiente

Copie o arquivo de exemplo para criar a sua configuração local:

```bash
cp config.example.json config.json
```

Ajuste os parâmetros do `config.json` com os dados do seu ramal/servidor SIP.

### 4. Inicializar e rodar

Inicializar o banco de dados SQLite:

```bash
python -c "from db import init_db; init_db()"
```

Iniciar a automação PJSIP (disparo de chamadas CLI):

```bash
python main.py
```

Iniciar o Dashboard Web:

```bash
python app.py
```

Consultar as chamadas salvas no banco de dados:

```bash
python ver_banco.py
```
