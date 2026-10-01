import os
import sqlite3 

def init_db(db_name="telecom.db"):
    """Cria a tabela de chamadas caso ainda não exista."""
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chamadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id TEXT,
            operadora TEXT,
            telefone TEXT,
            ip TEXT,
            ramal TEXT,
            cenario TEXT,
            status_code INTEGER,
            status_text TEXT,
            pdd_ms REAL,
            duracao_segundos REAL,
            audio_path TEXT,
            q850_cause INTEGER,
            data_hora DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def salvar_registro_chamada(call_obj, nome_audio=None, db_name="telecom.db"):
    """Insere os dados da chamada finalizada no SQLite."""
    init_db(db_name)

    # 1. Trata o caminho do arquivo de áudio
    caminho_audio = None
    if nome_audio:
        os.makedirs("audios", exist_ok=True)
        caminho_audio = os.path.join("audios", nome_audio)

    # 2. Calcula PDD (Post Dial Delay) se os timestamps existirem
    pdd_ms = None
    if call_obj.t_invite and call_obj.t_ring:
        pdd_ms = (call_obj.t_ring - call_obj.t_invite) * 1000
    elif call_obj.t_invite and call_obj.t_answer:
        pdd_ms = (call_obj.t_answer - call_obj.t_invite) * 1000

    # 3. Calcula Duração
    duracao_seg = 0
    if call_obj.t_answer and call_obj.t_end:
        duracao_seg = call_obj.t_end - call_obj.t_answer

    # 4. Grava no SQLite
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO chamadas (
            call_id, operadora, telefone, ip, ramal, cenario,
            status_code, status_text, pdd_ms, duracao_segundos,
            audio_path, q850_cause
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            str(call_obj.getId()),
            call_obj.operadora,
            call_obj.telefone,
            call_obj.ip,
            call_obj.ramal,
            call_obj.cenario,
            call_obj.last_status_code,
            call_obj.last_status_text,
            pdd_ms,
            duracao_seg,
            caminho_audio,
            call_obj.q850_cause,
        ),
    )

    conn.commit()
    conn.close()