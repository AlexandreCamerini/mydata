"""Um autenticador WebAuthn de software, para o teste.

Existe porque o gesto do autenticador não acontece sem navegador, e sem ele o
caminho de verificação — a parte que decide quem entra — iria para produção
sem nunca ter sido executado. Aqui ele é exercitado de verdade: chave ECDSA
P-256 gerada, `authenticatorData` montado byte a byte, assinatura conferida
pela mesma biblioteca que roda em produção.

Não é um substituto de testar num aparelho real, e não pretende ser: um
autenticador de verdade acrescenta presença de usuário, biometria e atestado
do fabricante. O que este cobre é exatamente o que o servidor confere.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.api.acesso import b64, de_b64

# Bandeiras do `authenticatorData`: presença de usuário, verificação de
# usuário, e dado de credencial anexado. As duas primeiras são o que o
# servidor exige; a terceira só existe no registro.
UP, UV, AT = 0x01, 0x04, 0x40


class Autenticador:
    """Uma chave, um `rp_id`, um contador. O bastante para os dois fluxos."""

    def __init__(self, rp_id: str = "localhost"):
        self.rp_id = rp_id
        self.chave = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.contador = 0
        self.aaguid = b"\x00" * 16

    # -- interno ----------------------------------------------------------
    def _cose(self) -> bytes:
        """A chave pública no formato COSE, que é como o WebAuthn a carrega."""
        nums = self.chave.public_key().public_numbers()
        return cbor2.dumps({
            1: 2,    # kty: EC2
            3: -7,   # alg: ES256
            -1: 1,   # crv: P-256
            -2: nums.x.to_bytes(32, "big"),
            -3: nums.y.to_bytes(32, "big"),
        })

    def _dados(self, bandeiras: int, com_credencial: bool) -> bytes:
        self.contador += 1
        saida = hashlib.sha256(self.rp_id.encode()).digest()
        saida += bytes([bandeiras])
        saida += struct.pack(">I", self.contador)
        if com_credencial:
            saida += self.aaguid
            saida += struct.pack(">H", len(self.credential_id))
            saida += self.credential_id
            saida += self._cose()
        return saida

    def _cliente(self, tipo: str, desafio: str, origem: str) -> bytes:
        return json.dumps({
            "type": tipo, "challenge": desafio, "origin": origem,
            "crossOrigin": False,
        }).encode()

    # -- os dois fluxos ---------------------------------------------------
    def registrar(self, opcoes_json: str, origem: str) -> dict:
        """O que `navigator.credentials.create()` devolveria."""
        opcoes = json.loads(opcoes_json)
        cliente = self._cliente("webauthn.create", opcoes["challenge"], origem)
        dados = self._dados(UP | UV | AT, com_credencial=True)
        # `fmt: none` é o que um autenticador de plataforma costuma mandar, e
        # é o que `attestation=none` nas opções pede.
        atestado = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": dados})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(cliente),
                "attestationObject": b64(atestado),
                "transports": ["internal"],
            },
        }

    def autenticar(self, opcoes_json: str, origem: str) -> dict:
        """O que `navigator.credentials.get()` devolveria."""
        opcoes = json.loads(opcoes_json)
        cliente = self._cliente("webauthn.get", opcoes["challenge"], origem)
        dados = self._dados(UP | UV, com_credencial=False)
        assinatura = self.chave.sign(
            dados + hashlib.sha256(cliente).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(cliente),
                "authenticatorData": b64(dados),
                "signature": b64(assinatura),
                "userHandle": None,
            },
        }

    def assinar_errado(self, opcoes_json: str, origem: str) -> dict:
        """Uma assertiva com assinatura de outra chave.

        Serve para provar que a verificação verifica: sem este caso, um
        `verify_authentication_response` que sempre passasse ficaria
        indistinguível de um que funciona.
        """
        resposta = self.autenticar(opcoes_json, origem)
        intruso = ec.generate_private_key(ec.SECP256R1())
        dados = de_b64(resposta["response"]["authenticatorData"])
        cliente = de_b64(resposta["response"]["clientDataJSON"])
        resposta["response"]["signature"] = b64(intruso.sign(
            dados + hashlib.sha256(cliente).digest(), ec.ECDSA(hashes.SHA256())
        ))
        return resposta
