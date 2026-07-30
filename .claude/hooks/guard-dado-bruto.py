#!/usr/bin/env python3
"""PreToolUse: protege o dado oficial da CVM. Só ele.

Exit 2 = chamada bloqueada; o stderr volta para o agente como feedback.
Exit 0 = segue.

O escopo é estreito de propósito. Imutável é o arquivo que a CVM publicou —
a única coisa aqui que não pode ser reconstruída. Silver, campos calculados e
gold são derivados e devem poder ser dropados e recomputados à vontade, porque
recomputar do bronze é a rotina normal de correção. Este hook não atrapalha
isso.
"""
from __future__ import annotations

import json
import re
import sys

# Caminhos cujo conteúdo é imutável depois de gravado.
BRONZE = re.compile(r"(^|/)(data/)?bronze/", re.IGNORECASE)

# DDL/DML contra as tabelas de captura do dado oficial — não contra derivadas.
SQL_BRONZE = re.compile(
    r"\b(drop\s+table|truncate\s+table|delete\s+from|update)\s+"
    r"(if\s+exists\s+)?[\w.\"]*\b(bronze|captura|raw)\w*",
    re.IGNORECASE,
)
# Remoção ou sobrescrita do arquivo oficial no filesystem.
FS_BRONZE = re.compile(
    r"\b(rm|shred|mv|truncate)\b[^;|&]*\bbronze\b|>\s*[^|;]*\bbronze/",
    re.IGNORECASE,
)

# Comandos de inspeção: só leem ou imprimem texto. Um `grep bronze` ou um teste
# que cita o SQL proibido não é uma tentativa de apagar nada.
INSPECAO = re.compile(
    r"^\s*(grep|rg|ag|cat|bat|less|head|tail|echo|printf|ls|find|wc|diff|"
    r"git\s+(status|diff|log|show))\b",
    re.IGNORECASE,
)


def bloquear(motivo: str) -> None:
    print(motivo, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        evento = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # sem payload legível, não interfere

    tool = evento.get("tool_name", "")
    entrada = evento.get("tool_input", {}) or {}

    if tool in ("Write", "Edit", "NotebookEdit"):
        caminho = str(entrada.get("file_path", ""))
        if BRONZE.search(caminho):
            bloquear(
                f"Bloqueado: {caminho} é dado oficial da CVM já capturado, e o "
                "bronze é imutável — é a única cópia que não dá para "
                "reconstruir. Uma nova captura vira um novo arquivo com novo "
                "hash. Se a intenção era corrigir um dado derivado, mexa em "
                "silver/gold ou recompute do bronze."
            )

    if tool == "Bash":
        cmd = str(entrada.get("command", ""))
        if INSPECAO.match(cmd):
            sys.exit(0)
        if SQL_BRONZE.search(cmd):
            bloquear(
                "Bloqueado: o comando altera ou remove as tabelas de captura do "
                "dado oficial. Tabelas derivadas (silver, calculados, gold) "
                "podem ser dropadas e recomputadas à vontade — só o bronze não. "
                "Se a remoção do bronze for mesmo necessária, peça ao usuário."
            )
        if FS_BRONZE.search(cmd):
            bloquear(
                "Bloqueado: o comando remove ou sobrescreve arquivo oficial "
                "capturado em bronze. Peça confirmação ao usuário antes."
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
