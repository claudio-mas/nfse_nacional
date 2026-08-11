"""Fixtures compartilhadas.

Todo material de chave usado nos testes é **gerado em tempo de execução**. Nada de
`.pfx` versionado: chave privada em repositório é um erro que não se desfaz com
`git rm`, e o `.gitignore` já bloqueia `*.pfx`, `*.p12`, `*.pem` e `*.key` justamente
para que um deslize não passe.

Os certificados aqui são auto-assinados e imitam a forma de um e-CNPJ ICP-Brasil A1
(`CN=RAZÃO SOCIAL:CNPJ`), o suficiente para exercitar carga, validade e mTLS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

SENHA = "senha-de-teste"
CN_EXEMPLO = "PETSHOP EXEMPLO LTDA:12345678000195"


@dataclass(frozen=True)
class PfxGerado:
    """Um `.pfx` em memória, com o que o teste precisa saber sobre ele."""

    blob: bytes
    senha: str
    cn: str
    nao_antes: datetime
    nao_depois: datetime


def _gerar_pfx(
    *,
    cn: str = CN_EXEMPLO,
    valido_de: timedelta = timedelta(days=-1),
    valido_ate: timedelta = timedelta(days=365),
    senha: str = SENHA,
) -> PfxGerado:
    agora = datetime.now(timezone.utc)
    nao_antes = agora + valido_de
    nao_depois = agora + valido_ate

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Brasil"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "AC Teste"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nao_antes)
        .not_valid_after(nao_depois)
        .sign(chave, hashes.SHA256())
    )

    blob = pkcs12.serialize_key_and_certificates(
        name=cn.encode("utf-8"),
        key=chave,
        cert=certificado,
        cas=None,
        encryption_algorithm=BestAvailableEncryption(senha.encode("utf-8")),
    )
    return PfxGerado(blob=blob, senha=senha, cn=cn, nao_antes=nao_antes, nao_depois=nao_depois)


@pytest.fixture(scope="session")
def pfx_valido() -> PfxGerado:
    """Certificado dentro da validade, com folga bem maior que os 30 dias de aviso."""
    return _gerar_pfx()


@pytest.fixture(scope="session")
def pfx_vencendo() -> PfxGerado:
    """Vence em 10 dias: dispara `precisa_renovar` sem estar vencido."""
    return _gerar_pfx(valido_ate=timedelta(days=10))


@pytest.fixture(scope="session")
def pfx_vencido() -> PfxGerado:
    """Venceu ontem."""
    return _gerar_pfx(valido_de=timedelta(days=-400), valido_ate=timedelta(days=-1))


@pytest.fixture(scope="session")
def pfx_futuro() -> PfxGerado:
    """Só passa a valer daqui a 10 dias — o outro lado de `vencido`."""
    return _gerar_pfx(valido_de=timedelta(days=10), valido_ate=timedelta(days=400))
