"""A camada de acesso do ADR-19 — sessão, passkey, e o token que fica.

O risco registrado desta decisão é trancar o dono fora do próprio sistema.
Quase todo teste aqui existe para isso: cada caminho de entrada que o ADR
promete manter aberto tem uma asserção que quebra se ele fechar.

O gesto do autenticador não dá para simular sem navegador — o que se testa é
tudo em volta dele: desafio de uso único, sessão com identidade e prazo,
revogação individual, e quando cada formulário aparece.
"""
from __future__ import annotations

import pytest

from app.api import acesso, auth


# --------------------------------------------------------------------------
# Sessão
# --------------------------------------------------------------------------
def test_sessao_carrega_identidade_e_prazo(sink):
    ident = acesso.abrir_sessao(sink, "passkey:chave do chaveiro")
    linha = acesso.sessao_valida(sink, ident)
    assert linha is not None
    # Identidade era a primeira das quatro faltas do §5.2: o token dizia que
    # alguém sabia o segredo, não quem entrou.
    assert linha["origem"] == "passkey:chave do chaveiro"
    assert linha["expira_em"] is not None


def test_sessao_desconhecida_nao_vale(sink):
    assert acesso.sessao_valida(sink, "inventada") is None
    assert acesso.sessao_valida(sink, None) is None


def test_sessao_vencida_e_recusada_e_apagada(sink):
    from datetime import datetime, timedelta, timezone

    ident = acesso.abrir_sessao(sink, "token")
    sink.executar(
        "UPDATE sessao_admin SET expira_em = ? WHERE id = ?",
        (datetime.now(timezone.utc) - timedelta(seconds=1), ident),
    )
    assert acesso.sessao_valida(sink, ident) is None
    # Não basta recusar: deixar a linha faria a tabela crescer com o que só
    # serve para ser recusado de novo.
    assert sink.um(
        "SELECT count(*) AS n FROM sessao_admin WHERE id = ?", (ident,)
    )["n"] == 0


def test_fechar_sessao_derruba_so_a_dela(sink):
    # A segunda falta do §5.2: trocar o token derrubava tudo ao mesmo tempo.
    a = acesso.abrir_sessao(sink, "token")
    b = acesso.abrir_sessao(sink, "passkey:telefone")
    acesso.fechar_sessao(sink, a)
    assert acesso.sessao_valida(sink, a) is None
    assert acesso.sessao_valida(sink, b) is not None


# --------------------------------------------------------------------------
# Desafio
# --------------------------------------------------------------------------
def test_desafio_serve_uma_vez(sink):
    bruto = acesso.novo_desafio(sink, "entrada")
    assert acesso.consumir_desafio(sink, acesso.b64(bruto), "entrada") == bruto
    with pytest.raises(acesso.ErroAcesso):
        acesso.consumir_desafio(sink, acesso.b64(bruto), "entrada")


def test_desafio_de_registro_nao_serve_para_entrar(sink):
    # Sem esta separação, um desafio obtido na tela de registro — que é
    # pública em nada, mas ainda assim outro fluxo — valeria para autenticar.
    bruto = acesso.novo_desafio(sink, "registro")
    with pytest.raises(acesso.ErroAcesso):
        acesso.consumir_desafio(sink, acesso.b64(bruto), "entrada")


def test_desafio_expirado_e_recusado(sink):
    from datetime import datetime, timedelta, timezone

    bruto = acesso.novo_desafio(sink, "entrada")
    sink.executar(
        "UPDATE desafio_webauthn SET criado_em = ? WHERE desafio = ?",
        (datetime.now(timezone.utc) - timedelta(hours=1), acesso.b64(bruto)),
    )
    with pytest.raises(acesso.ErroAcesso):
        acesso.consumir_desafio(sink, acesso.b64(bruto), "entrada")


def test_base64url_ida_e_volta():
    for n in range(1, 40):
        bruto = bytes(range(n))
        assert acesso.de_b64(acesso.b64(bruto)) == bruto
    # Sem `=` no fim: é o que o WebAuthn troca com o navegador.
    assert "=" not in acesso.b64(b"abcde")


# --------------------------------------------------------------------------
# Identidade do site
# --------------------------------------------------------------------------
def test_rp_id_sai_da_url_publica(monkeypatch):
    monkeypatch.setenv("PORTAL_URL_PUBLICA", "https://mydata.acamerini.app")
    rp, origens = acesso.identidade_do_site()
    assert rp == "mydata.acamerini.app"
    assert "https://mydata.acamerini.app" in origens


def test_origem_de_fora_nao_entra_na_lista(monkeypatch):
    """Só localhost é aceito além da URL pública.

    Se qualquer `Origin` recebido virasse origem aceita, a checagem de origem
    do WebAuthn deixaria de checar coisa alguma — seria conferir a resposta
    contra a pergunta que quem responde escolheu.
    """
    monkeypatch.setenv("PORTAL_URL_PUBLICA", "https://mydata.acamerini.app")
    _, origens = acesso.identidade_do_site("https://phishing.example")
    assert origens == ["https://mydata.acamerini.app"]


def test_sem_url_publica_cai_em_localhost(monkeypatch):
    monkeypatch.delenv("PORTAL_URL_PUBLICA", raising=False)
    rp, origens = acesso.identidade_do_site("http://localhost:8420")
    assert rp == "localhost"
    assert "http://localhost:8420" in origens


# --------------------------------------------------------------------------
# Passkey: registro, revogação e o que a tela oferece
# --------------------------------------------------------------------------
def _guardar_passkey(sink, ident="cred-1", rotulo="chave do chaveiro"):
    sink.executar(
        "INSERT INTO cfg_passkey (credential_id, chave_publica, sign_count, "
        "rotulo) VALUES (?,?,?,?)",
        (ident, b"\x01\x02\x03", 0, rotulo),
    )


def test_revogar_apaga_so_uma(sink):
    _guardar_passkey(sink, "a", "notebook")
    _guardar_passkey(sink, "b", "telefone")
    assert acesso.esquecer_passkey(sink, "a") is True
    assert [p["credential_id"] for p in acesso.passkeys(sink)] == ["b"]
    assert acesso.esquecer_passkey(sink, "a") is False


def test_credencial_desconhecida_nao_gasta_o_desafio(sink):
    """Quem tenta com credencial que não existe não pode invalidar o desafio
    de quem tem a certa — seria negação de serviço de graça."""
    bruto = acesso.novo_desafio(sink, "entrada")
    with pytest.raises(acesso.ErroAcesso):
        acesso.entrar_com_passkey(sink, {"id": "nao-existe"})
    assert acesso.consumir_desafio(sink, acesso.b64(bruto), "entrada") == bruto


def test_formulario_de_token_aparece_enquanto_nao_ha_passkey(sink, monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "x" * 43)
    monkeypatch.delenv("PORTAL_ACESSO_LEGADO", raising=False)
    # Sem esta regra o primeiro passkey nunca entraria: registrar exige
    # sessão, e a primeira sessão vem do token.
    assert acesso.token_no_formulario(sink) is True


def test_formulario_de_token_some_depois_do_primeiro_passkey(sink, monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "x" * 43)
    monkeypatch.delenv("PORTAL_ACESSO_LEGADO", raising=False)
    _guardar_passkey(sink)
    assert acesso.token_no_formulario(sink) is False


def test_acesso_legado_traz_o_formulario_de_volta(sink, monkeypatch):
    """A saída de emergência do ADR-19, testada.

    É a diferença entre reversível no papel e reversível às onze da noite pelo
    painel do Railway, com o autenticador perdido.
    """
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "x" * 43)
    monkeypatch.setenv("PORTAL_ACESSO_LEGADO", "1")
    _guardar_passkey(sink)
    assert acesso.token_no_formulario(sink) is True


def test_sem_token_configurado_nao_ha_formulario(sink, monkeypatch):
    monkeypatch.delenv("PORTAL_ADMIN_TOKEN", raising=False)
    assert acesso.token_no_formulario(sink) is False


# --------------------------------------------------------------------------
# O que continua valendo — a metade "aditiva" da decisão
# --------------------------------------------------------------------------
class _Pedido:
    """O mínimo de `Request` que `sessao_admin` lê."""

    def __init__(self, sink, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.app = type("A", (), {"state": type("S", (), {"sink": sink})()})()


def test_cabecalho_de_token_vale_sempre(sink, monkeypatch):
    """`X-Admin-Token` não passa por `token_no_formulario`.

    Quem opera por terminal não tem navegador e portanto não tem passkey. Se o
    cabeçalho caísse junto com o formulário, registrar um autenticador e
    perdê-lo trancaria o dono fora de tudo ao mesmo tempo.
    """
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "segredo-longo-o-bastante-para-servir")
    monkeypatch.delenv("PORTAL_ACESSO_LEGADO", raising=False)
    _guardar_passkey(sink)
    assert acesso.token_no_formulario(sink) is False
    pedido = _Pedido(sink,
                     headers={"X-Admin-Token": "segredo-longo-o-bastante-para-servir"})
    assert auth.sessao_admin(pedido) is True


def test_cookie_no_formato_antigo_continua_valendo(sink, monkeypatch):
    """Um cookie já emitido não pode parar de valer no deploy.

    Antes o cookie carregava o próprio token; agora carrega o id da sessão.
    Recusar o formato antigo derrubaria o dono no momento exato em que a
    mudança subisse.
    """
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "segredo-antigo-de-43-caracteres-ou-perto")
    pedido = _Pedido(
        sink,
        cookies={auth.COOKIE_SESSAO: "segredo-antigo-de-43-caracteres-ou-perto"},
    )
    assert auth.sessao_admin(pedido) is True


def test_cookie_de_sessao_nova_vale(sink, monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "x" * 43)
    ident = acesso.abrir_sessao(sink, "passkey:telefone")
    pedido = _Pedido(sink, cookies={auth.COOKIE_SESSAO: ident})
    assert auth.sessao_admin(pedido) is True


def test_cookie_qualquer_nao_vale(sink, monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "x" * 43)
    pedido = _Pedido(sink, cookies={auth.COOKIE_SESSAO: "chute"})
    assert auth.sessao_admin(pedido) is False


# --------------------------------------------------------------------------
# Ponta a ponta, pela HTTP
# --------------------------------------------------------------------------
TOKEN = "token-de-teste-longo-o-bastante-para-servir"


@pytest.fixture()
def portal(cliente, monkeypatch):
    """O mesmo cliente, agora com token configurado e sem chave de API.

    Sem tirar a chave, toda requisição passaria por `exigir_chave` e a camada
    de acesso humana nunca seria exercitada.
    """
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("PORTAL_ACESSO_LEGADO", raising=False)
    cliente.headers.pop("X-API-Key", None)
    return cliente


def test_raiz_sem_sessao_oferece_o_formulario(portal):
    r = portal.get("/", follow_redirects=False)
    assert r.status_code == 401
    assert 'name="token"' in r.text
    # Sem passkey registrada, o botão não aparece: oferecer o que não existe
    # manda o dono clicar para receber erro.
    assert "Entrar com passkey" not in r.text


def test_entrar_com_token_abre_sessao_com_origem(portal):
    r = portal.post("/entrar", data={"token": TOKEN, "destino": "/admin/"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/"
    biscoito = r.cookies.get(auth.COOKIE_SESSAO)
    assert biscoito and biscoito != TOKEN, "o cookie não carrega mais o segredo"
    sink = _sink_do(portal)
    assert acesso.sessao_valida(sink, biscoito)["origem"] == "token"


def test_token_errado_nao_abre_sessao(portal):
    r = portal.post("/entrar", data={"token": "chute", "destino": "/"},
                    follow_redirects=False)
    assert r.status_code == 401
    assert "Token inválido" in r.text


def test_destino_para_fora_e_ignorado(portal):
    """`//exemplo.com` é URL absoluta protocolo-relativa: sem a checagem, o
    formulário de entrada mandaria o dono para fora depois de autenticar."""
    r = portal.post("/entrar", data={"token": TOKEN, "destino": "//exemplo.com"},
                    follow_redirects=False)
    assert r.headers["location"] == "/"


def test_sair_apaga_a_linha_e_nao_so_o_cookie(portal):
    r = portal.post("/entrar", data={"token": TOKEN, "destino": "/"},
                    follow_redirects=False)
    ident = r.cookies.get(auth.COOKIE_SESSAO)
    portal.get("/sair", follow_redirects=False)
    assert acesso.sessao_valida(_sink_do(portal), ident) is None


def test_desafio_sem_passkey_responde_404_e_nao_500(portal):
    r = portal.post("/acesso/desafio")
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "sem_passkey"


def test_com_passkey_a_tela_troca_de_caminho(portal):
    _guardar_passkey(_sink_do(portal), "cred-web", "notebook")
    r = portal.get("/", follow_redirects=False)
    assert "Entrar com passkey" in r.text
    assert 'name="token"' not in r.text
    # E o POST do formulário some junto: aceitar o que a tela não oferece
    # manteria aberta a porta que ela diz estar fechada.
    r = portal.post("/entrar", data={"token": TOKEN, "destino": "/"},
                    follow_redirects=False)
    assert r.status_code == 401
    assert "desligado" in r.text


def test_acesso_legado_reabre_o_post_do_token(portal, monkeypatch):
    _guardar_passkey(_sink_do(portal), "cred-web", "notebook")
    monkeypatch.setenv("PORTAL_ACESSO_LEGADO", "1")
    r = portal.post("/entrar", data={"token": TOKEN, "destino": "/"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_registro_de_passkey_exige_sessao(portal):
    """Sem isto qualquer visitante registraria o próprio autenticador e
    passaria a ser dono. É o motivo de o token continuar existindo."""
    r = portal.post("/admin/api/acesso/passkeys/opcoes", json={"rotulo": "x"})
    assert r.status_code == 401


def test_com_sessao_as_opcoes_de_registro_saem(portal):
    portal.post("/entrar", data={"token": TOKEN, "destino": "/"},
                follow_redirects=False)
    r = portal.post("/admin/api/acesso/passkeys/opcoes", json={"rotulo": "notebook"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["challenge"] and corpo["rp"]["id"]


def test_painel_de_acesso_diz_qual_caminho_esta_aberto(portal):
    portal.post("/entrar", data={"token": TOKEN, "destino": "/"},
                follow_redirects=False)
    d = portal.get("/admin/api/acesso").json()["dados"]
    assert d["token_configurado"] is True
    assert d["token_no_formulario"] is True
    assert d["passkeys"] == []
    assert any(s["origem"] == "token" for s in d["sessoes"])


def test_revogar_passkey_pelo_cabecalho(portal):
    """Com passkey registrada, o formulário fecha e o cabeçalho fica.

    É por ele que se revoga o autenticador que não se tem mais em mãos — o
    caso exato do risco registrado no ADR-19. Sem esta rota funcionar por
    cabeçalho, perder o autenticador significaria não conseguir nem apagá-lo.
    """
    _guardar_passkey(_sink_do(portal), "cred-web", "notebook")
    assert portal.post("/entrar", data={"token": TOKEN, "destino": "/"},
                       follow_redirects=False).status_code == 401
    r = portal.delete("/admin/api/acesso/passkeys/cred-web",
                      headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200 and r.json()["dados"]["restantes"] == 0


def _sink_do(cliente):
    return cliente.app.state.sink if hasattr(cliente, "app") else _sink_global()


def _sink_global():
    from app.api.main import app

    return app.state.sink


# --------------------------------------------------------------------------
# O fluxo inteiro, com um autenticador de software
# --------------------------------------------------------------------------
# Sem isto, a parte que decide quem entra iria para produção sem nunca ter
# rodado: o gesto não acontece fora do navegador. `tests/autenticador.py`
# monta o `authenticatorData` byte a byte e assina com ECDSA P-256 — o que a
# biblioteca confere aqui é a mesma coisa que ela confere lá.
ORIGEM = "http://localhost:8420"


@pytest.fixture()
def autenticador(monkeypatch):
    from autenticador import Autenticador

    monkeypatch.delenv("PORTAL_URL_PUBLICA", raising=False)
    return Autenticador("localhost")


def test_registro_e_entrada_ponta_a_ponta(sink, autenticador, monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", "x" * 43)

    opcoes = acesso.opcoes_de_registro(sink, "notebook", ORIGEM)
    acesso.registrar(sink, autenticador.registrar(opcoes, ORIGEM),
                     "notebook", ORIGEM)

    guardadas = acesso.passkeys(sink)
    assert [p["rotulo"] for p in guardadas] == ["notebook"]
    # Registrada uma, o formulário de token sai da tela — e é justamente o
    # que só pode acontecer depois de o caminho novo funcionar.
    assert acesso.token_no_formulario(sink) is False

    desafio = acesso.opcoes_de_entrada(sink, ORIGEM)
    ident = acesso.entrar_com_passkey(
        sink, autenticador.autenticar(desafio, ORIGEM), ORIGEM
    )
    sessao = acesso.sessao_valida(sink, ident)
    assert sessao["origem"] == "passkey:notebook"
    # O contador subiu: é o que denuncia credencial clonada.
    assert acesso.passkeys(sink)[0]["sign_count"] > 0
    assert acesso.passkeys(sink)[0]["ultimo_uso_em"] is not None


def test_assinatura_de_outra_chave_e_recusada(sink, autenticador):
    opcoes = acesso.opcoes_de_registro(sink, "notebook", ORIGEM)
    acesso.registrar(sink, autenticador.registrar(opcoes, ORIGEM),
                     "notebook", ORIGEM)
    desafio = acesso.opcoes_de_entrada(sink, ORIGEM)
    with pytest.raises(acesso.ErroAcesso):
        acesso.entrar_com_passkey(
            sink, autenticador.assinar_errado(desafio, ORIGEM), ORIGEM
        )


def test_assertiva_nao_serve_duas_vezes(sink, autenticador):
    """Repetição é o ataque que o desafio existe para impedir."""
    opcoes = acesso.opcoes_de_registro(sink, "notebook", ORIGEM)
    acesso.registrar(sink, autenticador.registrar(opcoes, ORIGEM),
                     "notebook", ORIGEM)
    desafio = acesso.opcoes_de_entrada(sink, ORIGEM)
    resposta = autenticador.autenticar(desafio, ORIGEM)
    assert acesso.entrar_com_passkey(sink, resposta, ORIGEM)
    with pytest.raises(acesso.ErroAcesso):
        acesso.entrar_com_passkey(sink, resposta, ORIGEM)


def test_assertiva_de_outra_origem_e_recusada(sink, autenticador, monkeypatch):
    """A origem faz parte do que foi assinado.

    É o que separa passkey de senha: uma credencial fica presa ao domínio, e
    um site clonado não consegue usá-la nem com a vítima colaborando.
    """
    opcoes = acesso.opcoes_de_registro(sink, "notebook", ORIGEM)
    acesso.registrar(sink, autenticador.registrar(opcoes, ORIGEM),
                     "notebook", ORIGEM)
    desafio = acesso.opcoes_de_entrada(sink, ORIGEM)
    resposta = autenticador.autenticar(desafio, "https://clone.example")
    with pytest.raises(acesso.ErroAcesso):
        acesso.entrar_com_passkey(sink, resposta, ORIGEM)


def test_revogado_nao_entra_mais(sink, autenticador):
    opcoes = acesso.opcoes_de_registro(sink, "notebook", ORIGEM)
    acesso.registrar(sink, autenticador.registrar(opcoes, ORIGEM),
                     "notebook", ORIGEM)
    acesso.esquecer_passkey(sink, acesso.b64(autenticador.credential_id))
    desafio = acesso.opcoes_de_entrada(sink, ORIGEM)
    with pytest.raises(acesso.ErroAcesso):
        acesso.entrar_com_passkey(
            sink, autenticador.autenticar(desafio, ORIGEM), ORIGEM
        )


def test_segundo_autenticador_convive_com_o_primeiro(sink, monkeypatch):
    """A saída número 1 do risco do ADR-19: mais de um registrado.

    Se registrar o segundo derrubasse o primeiro, a recomendação da tela
    ("registre outro antes de precisar") seria um conselho que quebra o
    sistema de quem o segue.
    """
    from autenticador import Autenticador

    monkeypatch.delenv("PORTAL_URL_PUBLICA", raising=False)
    a, b = Autenticador("localhost"), Autenticador("localhost")
    for aut, rotulo in ((a, "notebook"), (b, "telefone")):
        opcoes = acesso.opcoes_de_registro(sink, rotulo, ORIGEM)
        acesso.registrar(sink, aut.registrar(opcoes, ORIGEM), rotulo, ORIGEM)

    assert len(acesso.passkeys(sink)) == 2
    for aut, rotulo in ((a, "notebook"), (b, "telefone")):
        desafio = acesso.opcoes_de_entrada(sink, ORIGEM)
        ident = acesso.entrar_com_passkey(
            sink, aut.autenticar(desafio, ORIGEM), ORIGEM
        )
        assert acesso.sessao_valida(sink, ident)["origem"] == f"passkey:{rotulo}"

    # E revogar um deixa o outro de pé.
    acesso.esquecer_passkey(sink, acesso.b64(a.credential_id))
    desafio = acesso.opcoes_de_entrada(sink, ORIGEM)
    assert acesso.entrar_com_passkey(sink, b.autenticar(desafio, ORIGEM), ORIGEM)
