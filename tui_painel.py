# -*- coding: utf-8 -*-
"""
Substituto de registro.PainelAoVivo para uso com a interface Textual.

Mantém a MESMA interface pública (atualizar / registrar / __enter__ / __exit__),
então teste.py e os módulos em baterias/ não precisam de nenhuma alteração —
eles continuam chamando painel.atualizar(...) e painel.registrar(...) normalmente.

A diferença é que, em vez de desenhar a tabela Rich sozinho, este painel envia
as atualizações para o SipTesterApp (Textual) via app.call_from_thread, porque
o loop de eventos do pjsua2 roda numa thread separada da thread de UI.
"""
import csv
import datetime
import os


class PainelTUI:

    def __init__(self, app, csv_filename="resultado_chamadas.csv"):
        self.app = app
        self.csv_filename = os.path.abspath(csv_filename)
        self.headers = [
            "Data",
            "Horário",
            "Ramal",
            "Operadora",
            "Fornecedores",
            "PDD (s)",
            "Tempo de Ligação",
            "SIP_CODE",
            "SIP_REASON",
            "Atendida",
            "Número",
        ]
        self._init_csv()

    def _init_csv(self):
        try:
            if not os.path.exists(self.csv_filename):
                with open(
                    self.csv_filename, mode="w", newline="", encoding="utf-8-sig"
                ) as f:
                    writer = csv.writer(f)
                    writer.writerow(self.headers)
        except Exception as e:
            self._log(f"[bold red]Não foi possível criar o CSV: {e}[/bold red]")

    def _log(self, texto):
        if self.app:
            self.app.call_from_thread(self.app.log_thread_safe, texto)

    def atualizar(self, ramal, destino, operadora, status, codigo_sip):
        """Chamado a cada mudança de estado da chamada (CALLING, EARLY, CONFIRMED...)."""
        texto = (
            f"[dim]{ramal} → {destino} [{operadora}][/dim] "
            f"status=[cyan]{status}[/cyan] sip=[yellow]{codigo_sip}[/yellow]"
        )
        self._log(texto)

    def registrar(self, row_data):
        """Escreve no CSV (lógica idêntica à do PainelAoVivo original) e
        manda a linha final pra tabela de histórico na UI."""
        try:
            file_exists = os.path.exists(self.csv_filename)

            raw_ts = row_data.get("timestamp") or row_data.get("DataHorario")
            data_str, horario_str = "", ""

            if isinstance(raw_ts, (datetime.datetime, datetime.date)):
                data_str = raw_ts.strftime("%Y-%m-%d")
                horario_str = (
                    raw_ts.strftime("%H:%M:%S")
                    if isinstance(raw_ts, datetime.datetime)
                    else ""
                )
            elif isinstance(raw_ts, str) and " " in raw_ts:
                data_str, horario_str = raw_ts.split(" ", 1)
            elif isinstance(raw_ts, str) and "T" in raw_ts:
                data_str, horario_str = raw_ts.split("T", 1)
            else:
                data_str = row_data.get("Data", str(raw_ts) if raw_ts else "")
                horario_str = row_data.get("Horário", "")

            ramal = row_data.get("Ramal") or row_data.get("ramal", "")
            operadora = row_data.get("Operadora") or row_data.get("operadora", "")
            fornecedores = row_data.get("Fornecedores") or row_data.get("tronco", "")
            pdd = row_data.get("PDD (s)") or row_data.get("pdd_s", "")
            tempo_ligacao = (
                row_data.get("Tempo de Ligação")
                or row_data.get("audio_duration_s")
                or row_data.get("setup_time_s", "")
            )
            sip_code = row_data.get("SIP_CODE") or row_data.get("sip_code", "")
            sip_reason = row_data.get("SIP_REASON") or row_data.get("sip_reason", "")
            atendida = (
                row_data.get("Atendida")
                or row_data.get("classificacao")
                or row_data.get("atendida", "")
            )
            numero = (
                row_data.get("Número")
                or row_data.get("numero")
                or row_data.get("destino", "")
            )

            linha_formatada = [
                data_str,
                horario_str,
                ramal,
                operadora,
                fornecedores,
                pdd,
                tempo_ligacao,
                sip_code,
                sip_reason,
                atendida,
                numero,
            ]

            with open(
                self.csv_filename, mode="a", newline="", encoding="utf-8-sig"
            ) as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(self.headers)
                writer.writerow(linha_formatada)
                f.flush()
                os.fsync(f.fileno())

        except Exception as e:
            self._log(f"[bold red]Erro ao gravar CSV: {e}[/bold red]")

        if self.app:
            self.app.call_from_thread(self.app.adicionar_resultado, row_data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False