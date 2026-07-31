#!/usr/bin/env python
"""Sobe, consulta e para o portal local sem pisar em serviço de outro projeto.

Existe por causa de dois erros cometidos nesta máquina:

1. Um `uvicorn` subiu por fora do harness, ficou órfão numa sessão anterior e
   respondia com código velho — pior que estar fora do ar, porque parecia no ar.
2. A porta foi liberada com um `kill` cego, sem verificar de quem era o
   processo. Nesta máquina há pelo menos oito serviços em escuta.

Duas regras, e as duas são o motivo do arquivo existir:

- **Nunca matar processo que não é nosso.** "Nosso" é processo cujo diretório
  de trabalho é este repositório — não é a porta que define dono.
- **Nunca cair em outra porta em silêncio.** Se a porta está tomada por
  terceiro, isso é erro com nome e PID, não um número diferente escolhido por
  conta própria. Servidor em porta que ninguém sabe qual é foi exatamente o
  que já desorientou uma vez.

Uso:
    python scripts/servidor.py subir     # respeita quem já está no ar
    python scripts/servidor.py status
    python scripts/servidor.py parar
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Porta reservada para este projeto. Trocar aqui e em .claude/launch.json —
# há um teste que falha se os dois divergirem.
PORTA_PADRAO = 8420
BANCO_PADRAO = "dados/demo.duckdb"


def porta() -> int:
    return int(os.getenv("PORTAL_PORTA", PORTA_PADRAO))


# --------------------------------------------------------------------------
# Quem está na porta
# --------------------------------------------------------------------------
def _lsof(*args: str) -> str:
    try:
        return subprocess.run(
            ["lsof", *args], capture_output=True, text=True, timeout=10
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def pids_na_porta(p: int) -> list[int]:
    saida = _lsof("-nP", f"-iTCP:{p}", "-sTCP:LISTEN", "-t")
    return [int(x) for x in saida.split() if x.strip().isdigit()]


def diretorio_do(pid: int) -> str | None:
    """Diretório de trabalho do processo — é o que diz se ele é nosso."""
    for linha in _lsof("-a", "-p", str(pid), "-d", "cwd", "-Fn").splitlines():
        if linha.startswith("n"):
            return linha[1:]
    return None


def comando_do(pid: int) -> str:
    try:
        return subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "(desconhecido)"


def e_nosso(pid: int) -> bool:
    cwd = diretorio_do(pid)
    return bool(cwd) and Path(cwd).resolve() == RAIZ


def ocupantes(p: int) -> tuple[list[int], list[int]]:
    """(nossos, de terceiros) — separados antes de qualquer decisão."""
    nossos, alheios = [], []
    for pid in pids_na_porta(p):
        (nossos if e_nosso(pid) else alheios).append(pid)
    return nossos, alheios


def nossos_em_escuta() -> dict[int, list[int]]:
    """Todo processo deste repositório escutando alguma porta: {pid: [portas]}.

    Procurar só na porta esperada não basta. Esta função nasceu de encontrar,
    nesta máquina, um servidor deste mesmo repositório escutando em 8123 com
    `--host 0.0.0.0`, sobrevivente de outra sessão e servindo código velho.
    Órfão em porta que ninguém lembra é justamente o que não aparece quando se
    olha para onde ele deveria estar.
    """
    achados: dict[int, list[int]] = {}
    for linha in _lsof("-nP", "-iTCP", "-sTCP:LISTEN", "-FpPn").splitlines():
        if linha.startswith("p"):
            pid_corrente = int(linha[1:])
        elif linha.startswith("n") and ":" in linha:
            porta_txt = linha.rsplit(":", 1)[-1]
            if porta_txt.isdigit() and e_nosso(pid_corrente):
                achados.setdefault(pid_corrente, [])
                if int(porta_txt) not in achados[pid_corrente]:
                    achados[pid_corrente].append(int(porta_txt))
    return achados


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------
def cmd_status(_args) -> int:
    p = porta()
    nossos, alheios = ocupantes(p)
    print(f"porta {p} (reservada para este projeto)")
    if not nossos and not alheios:
        print("  livre")
    for pid in nossos:
        print(f"  NOSSO    pid {pid}  {comando_do(pid)}")
        print(f"           http://127.0.0.1:{p}/  ·  /admin/  ·  /docs")
    for pid in alheios:
        print(f"  DE OUTRO pid {pid}  cwd={diretorio_do(pid)}")
        print(f"           {comando_do(pid)}")

    orfaos = {pid: portas for pid, portas in nossos_em_escuta().items()
              if p not in portas}
    if orfaos:
        print("\nórfãos deste repositório em outras portas:")
        for pid, portas in orfaos.items():
            print(f"  pid {pid}  portas {portas}  {comando_do(pid)}")
        print("  → `python scripts/servidor.py parar --orfaos` derruba todos")
    return 0


def cmd_subir(args) -> int:
    p = porta()
    nossos, alheios = ocupantes(p)

    if alheios:
        print(
            f"porta {p} está ocupada por processo de outro projeto:", file=sys.stderr
        )
        for pid in alheios:
            print(f"  pid {pid}  cwd={diretorio_do(pid)}", file=sys.stderr)
            print(f"           {comando_do(pid)}", file=sys.stderr)
        print(
            "\nNão vou derrubar nem escolher outra porta por conta própria.\n"
            "Pare aquele serviço, ou rode com PORTAL_PORTA=<outra>.",
            file=sys.stderr,
        )
        return 2

    if nossos and not args.reiniciar:
        print(f"já está no ar em http://127.0.0.1:{p}/ (pid {nossos[0]})")
        print("use --reiniciar para trocar o processo pelo código atual")
        return 0

    if nossos:
        cmd_parar(args)

    banco = os.getenv("PORTAL_DUCKDB", BANCO_PADRAO)
    if not (RAIZ / banco).exists() and "DATABASE_URL" not in os.environ:
        print(
            f"banco '{banco}' não existe. Rode `python scripts/demo.py` "
            f"para criar uma base local com dado de exemplo.",
            file=sys.stderr,
        )
        return 3

    ambiente = {**os.environ, "PORTAL_DUCKDB": banco}
    print(f"subindo em http://127.0.0.1:{p}/  (banco: {banco})")
    return subprocess.call(
        [sys.executable, "-m", "uvicorn", "app.api.main:app",
         "--host", "127.0.0.1", "--port", str(p),
         *(["--reload"] if args.reload else [])],
        cwd=RAIZ, env=ambiente,
    )


def cmd_parar(args) -> int:
    import signal
    import time

    p = porta()
    nossos, alheios = ocupantes(p)
    if alheios:
        print(
            f"porta {p} tem processo de outro projeto (pid {alheios}); "
            f"não é meu para parar.", file=sys.stderr
        )
    alvos = list(nossos)
    if getattr(args, "orfaos", False):
        alvos += [pid for pid in nossos_em_escuta() if pid not in alvos]

    if not alvos:
        print(f"nada nosso na porta {p}")
        return 0
    for pid in alvos:
        os.kill(pid, signal.SIGTERM)
        print(f"parado: pid {pid}")
    # SIGKILL só no que não morreu por bem, e só no que já foi conferido nosso.
    time.sleep(1.5)
    for pid in alvos:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        os.kill(pid, signal.SIGKILL)
        print(f"forçado: pid {pid}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="servidor", description="Portal local, sem colidir com outros projetos"
    )
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("subir", help="sobe o portal (respeita quem já está no ar)")
    s.add_argument("--reiniciar", action="store_true",
                   help="derruba o nosso processo antes de subir")
    s.add_argument("--reload", action="store_true", help="recarrega ao editar")
    s.set_defaults(func=cmd_subir)

    sub.add_parser("status", help="quem está na porta").set_defaults(func=cmd_status)
    d = sub.add_parser("parar", help="para só o que é nosso")
    d.add_argument("--orfaos", action="store_true",
                   help="inclui processos deste repo em qualquer porta")
    d.set_defaults(func=cmd_parar)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
