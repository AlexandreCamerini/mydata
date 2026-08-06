"""Fase 5 — prontidão para o Railway.

Testa as invariantes de deploy que quebram silenciosamente em produção:
porta injetada, banco por variável, healthcheck sem banco, ausência de
estado em disco e configuração versionada coerente.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Configuração de deploy
# --------------------------------------------------------------------------
def test_railway_json_e_valido_e_aponta_para_o_healthcheck():
    cfg = json.loads((RAIZ / "railway.json").read_text())
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert cfg["deploy"]["healthcheckPath"] == "/health"
    assert "scripts/entrada.sh" in cfg["deploy"]["startCommand"]


def test_entrada_migra_antes_de_servir_e_separa_os_papeis():
    """Web e cron rodam a mesma imagem e diferem por variável.

    Migrar antes de servir: senão o primeiro request encontra tabela ausente.
    O papel desconhecido tem de falhar alto — um typo em PORTAL_PAPEL que
    caísse silenciosamente em `web` colocaria um segundo servidor no ar,
    ligado 24x7, no lugar do cron.
    """
    texto = (RAIZ / "scripts" / "entrada.sh").read_text()
    assert "app.cli migrar" in texto
    assert "app.cli agendados" in texto
    assert "${PORT:-8000}" in texto
    assert "exit 64" in texto


def test_imagem_contem_tudo_que_o_startcommand_referencia():
    """O startCommand aponta para um arquivo; arquivo fora da imagem é deploy
    que sobe e morre com "cannot open". Aconteceu uma vez."""
    cfg = json.loads((RAIZ / "railway.json").read_text())
    dockerfile = (RAIZ / "Dockerfile").read_text()
    for palavra in cfg["deploy"]["startCommand"].split():
        if "/" in palavra and not palavra.startswith("-"):
            assert palavra in dockerfile, (
                f"o startCommand usa '{palavra}', que o Dockerfile não copia"
            )


def test_dockerfile_nao_fixa_porta_e_nao_roda_como_root():
    texto = (RAIZ / "Dockerfile").read_text()
    assert "${PORT:-8000}" in texto, "a porta tem de vir do ambiente"
    assert re.search(r"^USER (?!root)", texto, re.M), "não rodar como root"
    assert "--from=front /web/dist" in texto, "o front sai na mesma imagem"


def test_env_example_documenta_toda_variavel_lida_pelo_codigo():
    """Variável nova sem documentação vira surpresa no deploy."""
    exemplo = (RAIZ / ".env.example").read_text()
    lidas: set[str] = set()
    for arquivo in (RAIZ / "app").rglob("*.py"):
        lidas |= set(re.findall(r"getenv\(\s*[\"']([A-Z_]+)[\"']", arquivo.read_text()))
    nao_documentadas = {v for v in lidas if v not in exemplo}
    assert not nao_documentadas, f"faltam no .env.example: {nao_documentadas}"


def test_requisitos_de_runtime_sao_enxutos():
    """pandas e duckdb são de desenvolvimento — não vão para a imagem."""
    pacotes = {
        re.split(r"[><=\[]", linha, maxsplit=1)[0].strip().lower()
        for linha in (RAIZ / "requisitos.txt").read_text().splitlines()
        if linha.strip() and not linha.strip().startswith("#")
    }
    assert "pandas" not in pacotes
    assert "duckdb" not in pacotes
    assert {"fastapi", "psycopg"} <= pacotes


# --------------------------------------------------------------------------
# Comportamento em runtime
# --------------------------------------------------------------------------
def test_sink_segue_a_database_url(monkeypatch):
    from app.sinks import criar_sink

    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@127.0.0.1:1/z")
    with pytest.raises(Exception):
        # Sem Postgres de pé isto falha — o que importa é que ele tentou
        # Postgres, e não caiu silenciosamente no DuckDB.
        criar_sink()


def test_sem_database_url_usa_duckdb(monkeypatch, tmp_path):
    from app.sinks import SinkDuckDB, criar_sink

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PORTAL_DUCKDB", str(tmp_path / "x.duckdb"))
    sink = criar_sink()
    assert isinstance(sink, SinkDuckDB)
    sink.fechar()


def test_health_nao_toca_no_banco(monkeypatch, tmp_path):
    """O healthcheck do Railway não pode depender do banco: se depender,
    uma lentidão no Postgres derruba o serviço inteiro."""
    from fastapi.testclient import TestClient

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PORTAL_DUCKDB", str(tmp_path / "h.duckdb"))
    from app.api.main import app

    with TestClient(app) as c:
        # Derruba o sink de propósito; /health tem de continuar respondendo.
        app.state.sink.fechar()
        r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_nada_escreve_em_disco_fora_do_banco():
    """Filesystem do container é efêmero: nenhum caminho fixo de escrita."""
    suspeitos = []
    for arquivo in (RAIZ / "app").rglob("*.py"):
        texto = arquivo.read_text()
        for m in re.finditer(r"open\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"'][wa]", texto):
            suspeitos.append(f"{arquivo.name}: {m.group(1)}")
    assert not suspeitos, f"escrita em caminho fixo: {suspeitos}"


def test_cli_expoe_os_comandos_que_o_cron_usa():
    from app.cli import main

    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0


def test_agendamentos_cobrem_os_datasets_configurados(sink_cvm):
    from app import repositorio as repo

    agendados = {a["dataset_chave"] for a in repo.listar_agendamentos(sink_cvm)}
    configurados = {d["chave"] for d in repo.listar_datasets(sink_cvm)}
    assert configurados <= agendados, (
        f"dataset sem agendamento nunca será atualizado: {configurados - agendados}"
    )


def test_cron_do_itr_e_trimestral(sink_cvm):
    from app import repositorio as repo

    itr = [a for a in repo.listar_agendamentos(sink_cvm)
           if a["dataset_chave"] == "cvm_itr"][0]
    meses = itr["cron"].split()[3]
    assert len(meses.split(",")) == 4, "ITR sai quatro vezes por ano"


# --------------------------------------------------------------------------
# Portas locais
# --------------------------------------------------------------------------
def test_launch_json_e_servidor_concordam_na_porta():
    """A porta vive em dois lugares: o script e o launch.json do harness.
    Divergirem significa `preview_start` abrindo o navegador numa porta e o
    servidor subindo em outra."""
    import sys

    sys.path.insert(0, str(RAIZ / "scripts"))
    import servidor

    cfg = json.loads((RAIZ / ".claude" / "launch.json").read_text())
    portas = {c["port"] for c in cfg["configurations"]}
    assert portas == {servidor.PORTA_PADRAO}


def test_launch_json_sobe_pelo_gestor_e_nao_por_uvicorn_direto():
    """Chamar uvicorn direto pelo launch.json contornaria a checagem de dono
    da porta — que é a razão de o gestor existir."""
    cfg = json.loads((RAIZ / ".claude" / "launch.json").read_text())
    for c in cfg["configurations"]:
        assert "scripts/servidor.py" in " ".join(c["runtimeArgs"])


def test_dono_da_porta_e_o_diretorio_nao_a_porta():
    """`e_nosso` decide quem pode ser derrubado. Errar para o lado permissivo
    aqui significa matar serviço de outro projeto do Alex."""
    import os
    import sys

    sys.path.insert(0, str(RAIZ / "scripts"))
    import servidor

    # O próprio pytest roda com cwd na raiz do repositório.
    assert servidor.e_nosso(os.getpid()) is True
    # launchd (pid 1) roda em "/" e nunca pode ser considerado nosso.
    assert servidor.e_nosso(1) is False
    # PID inexistente não é nosso — e não pode estourar.
    assert servidor.e_nosso(999_999) is False


# --------------------------------------------------------------------------
# Bronze comprimido (ADR-21)
# --------------------------------------------------------------------------
def test_a_compressao_do_bronze_e_so_postgres():
    """`STORAGE` não existe no DuckDB.

    A migração precisa ser vazia no dialeto de desenvolvimento em vez de
    condicional no código — é o que `so_postgres` existe para expressar, e
    escondê-la num `if` faria a suíte local passar por não ter rodado nada."""
    from app.migracoes import MIGRACOES

    mig = next(m for m in MIGRACOES if m.nome == "0017_bronze_comprimido")
    assert mig.sql == []
    assert any("SET STORAGE EXTENDED" in s for s in mig.so_postgres)


def test_a_compressao_vem_depois_de_quem_cria_a_tabela():
    """Ordem importa: `ALTER` antes do `CREATE` quebraria o banco novo."""
    from app.migracoes import MIGRACOES

    nomes = [m.nome for m in MIGRACOES]
    assert nomes.index("0003_bronze") < nomes.index("0017_bronze_comprimido")


def test_a_premissa_do_storage_external_esta_registrada():
    """A `0003` desliga a compressão com um comentário que era verdade — "ZIP
    já vem comprimido". O cadastro de instrumentos entrega CSV puro e quebrou a
    premissa. Se alguém reverter para EXTERNAL sem passar pelo ADR-21, este
    teste é o que pergunta por quê."""
    from app.migracoes import MIGRACOES

    ext = [s for m in MIGRACOES for s in m.so_postgres if "SET STORAGE" in s]
    assert ext[-1].endswith("EXTENDED"), (
        "a última palavra sobre STORAGE do payload é do ADR-21: EXTENDED. "
        f"Encontrado: {ext}"
    )


def test_migracao_nova_roda_e_registra_no_duckdb(tmp_path):
    """Mesmo sem SQL no dialeto local, a migração precisa entrar em
    `schema_migracao` — senão ela é tentada de novo a cada boot."""
    from app import migracoes
    from app.sinks import SinkDuckDB

    s = SinkDuckDB(str(tmp_path / "m.duckdb"))
    try:
        migracoes.aplicar(s)
        aplicadas = {l["nome"] for l in s.consultar("SELECT nome FROM schema_migracao")}
        assert "0017_bronze_comprimido" in aplicadas
        # Idempotente: a segunda passada não repete nada.
        assert migracoes.aplicar(s) == []
    finally:
        s.fechar()
