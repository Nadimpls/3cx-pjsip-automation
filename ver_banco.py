import os
import sqlite3

DB_NAME = "telecom.db"


def consultar_banco():
    if not os.path.exists(DB_NAME):
        print(f"❌ O arquivo '{DB_NAME}' ainda não existe no diretório.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        # Conta o total de registros
        cursor.execute("SELECT COUNT(*) FROM chamadas;")
        total = cursor.fetchone()[0]

        print(f"📊 Total de chamadas gravadas: {total}\n")

        if total == 0:
            print("⚠️ A tabela existe, mas o banco está VAZIO.")
            return

        # Busca as últimas 10 chamadas registradas
        cursor.execute("""
            SELECT id, operadora, telefone, status_code, status_text, pdd_ms, duracao_segundos, audio_path, data_hora 
            FROM chamadas 
            ORDER BY id DESC 
            LIMIT 10
        """)

        linhas = cursor.fetchall()

        # Exibe os resultados formatados
        cabecalho = f"{'ID':<4} | {'Operadora':<10} | {'Telefone':<12} | {'Status':<6} | {'PDD (ms)':<9} | {'Dur (s)':<7} | {'Áudio':<25} | {'Data/Hora'}"
        print(cabecalho)
        print("-" * len(cabecalho))

        for row in linhas:
            call_id = row[0]
            op = str(row[1] or "N/A")
            tel = str(row[2] or "N/A")
            status = row[3] or "N/A"
            pdd = f"{row[5]:.1f}" if row[5] is not None else "N/A"
            dur = f"{row[6]:.1f}" if row[6] is not None else "0.0"
            audio = str(row[7] or "Sem áudio")
            data = str(row[8])

            print(
                f"{call_id:<4} | {op:<10} | {tel:<12} | {status:<6} | {pdd:<9} | {dur:<7} | {audio:<25} | {data}"
            )

    except sqlite3.OperationalError as e:
        print(
            f"❌ Erro ao acessar a tabela: {e}. Certifique-se de que a tabela 'chamadas' foi criada via init_db()."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    consultar_banco()