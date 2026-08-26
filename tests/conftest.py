"""Fixtures compartilhadas.

Todo material de chave usado nos testes é **gerado em tempo de execução**. Nada de
`.pfx` versionado: chave privada em repositório é um erro que não se desfaz com
`git rm`, e o `.gitignore` já bloqueia `*.pfx`, `*.p12`, `*.pem` e `*.key` justamente
para que um deslize não passe.

Os certificados aqui são auto-assinados e imitam a forma de um e-CNPJ ICP-Brasil A1, o
suficiente para exercitar carga, validade e mTLS.

`CN=RAZÃO SOCIAL:CNPJ` é só uma das três formas em que o CNPJ aparece, e por um tempo foi
a única que este arquivo gerava — o que fez os testes confirmarem a convenção que eles
mesmos escreviam, em vez de testar a leitura. As fixtures no fim do arquivo cobrem as
outras duas (`otherName` do SAN e `2.5.4.97`) e os casos em que elas discordam.
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


OID_ICP_CNPJ = x509.ObjectIdentifier("2.16.76.1.3.3")
OID_ICP_CPF = x509.ObjectIdentifier("2.16.76.1.3.1")
OID_ORGANIZATION_IDENTIFIER = x509.ObjectIdentifier("2.5.4.97")


TAG_OCTET_STRING = 0x04
TAG_PRINTABLE_STRING = 0x13


def _der_string(texto: str, tag: int = TAG_PRINTABLE_STRING) -> bytes:
    """O valor DER que vai dentro do `otherName`.

    O tipo de string **varia entre emissores**: um `.pfx` de teste real trouxe
    `PrintableString` (`0x13`), e este arquivo por um tempo só gerava `OCTET STRING`
    (`0x04`) — o que teria deixado passar uma implementação que só soubesse ler um dos
    dois. Por isso o tag é parâmetro, e as duas codificações têm fixture.
    """
    bruto = texto.encode("ascii")
    return bytes([tag, len(bruto)]) + bruto


def _gerar_pfx(
    *,
    cn: str = CN_EXEMPLO,
    valido_de: timedelta = timedelta(days=-1),
    valido_ate: timedelta = timedelta(days=365),
    senha: str = SENHA,
    cnpj_no_othername: str | None = None,
    cnpj_no_org_id: str | None = None,
    cpf_no_othername: str | None = None,
    tag_othername: int = TAG_PRINTABLE_STRING,
) -> PfxGerado:
    """Um `.pfx` auto-assinado.

    Os três últimos parâmetros existem porque um e-CNPJ ICP-Brasil pode trazer o CNPJ em
    até três lugares — `otherName` do SAN (normativo), `2.5.4.97`, e o `CN` — e eles nem
    sempre concordam. Poder montar cada combinação é o que permite testar a ordem de
    autoridade de `Certificate.cnpj` em vez de confirmar a convenção que este arquivo
    mesmo escreve.
    """
    agora = datetime.now(timezone.utc)
    nao_antes = agora + valido_de
    nao_depois = agora + valido_ate

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    atributos = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Brasil"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "AC Teste"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ]
    if cnpj_no_org_id is not None:
        atributos.append(x509.NameAttribute(OID_ORGANIZATION_IDENTIFIER, f"CNPJ:{cnpj_no_org_id}"))
    nome = x509.Name(atributos)

    construtor = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nao_antes)
        .not_valid_after(nao_depois)
    )

    nomes_alternativos: list[x509.GeneralName] = []
    if cnpj_no_othername is not None:
        nomes_alternativos.append(
            x509.OtherName(OID_ICP_CNPJ, _der_string(cnpj_no_othername, tag_othername))
        )
    if cpf_no_othername is not None:
        nomes_alternativos.append(x509.OtherName(OID_ICP_CPF, _der_string(cpf_no_othername)))
    if nomes_alternativos:
        construtor = construtor.add_extension(
            x509.SubjectAlternativeName(nomes_alternativos), critical=False
        )

    certificado = construtor.sign(chave, hashes.SHA256())

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


@pytest.fixture(scope="session")
def pfx_cnpj_no_othername() -> PfxGerado:
    """CNPJ só no lugar normativo (`otherName`, OID 2.16.76.1.3.3), sem repetir no CN.

    É o certificado que o código antigo não conseguia ler — e é a forma que E1209 cobra.
    """
    return _gerar_pfx(cn="EMPRESA SEM CNPJ NO CN LTDA", cnpj_no_othername="12345678000195")


@pytest.fixture(scope="session")
def pfx_cnpj_so_no_org_id() -> PfxGerado:
    """CNPJ só em `2.5.4.97`, como `CNPJ:...`. É o formato do `cert_a1_teste.pfx`."""
    return _gerar_pfx(cn="EMPRESA TESTE LTDA - A1 FAKE", cnpj_no_org_id="12345678000195")


@pytest.fixture(scope="session")
def pfx_cnpjs_discordantes() -> PfxGerado:
    """Os três lugares preenchidos, cada um com um CNPJ diferente.

    Existe para travar a **ordem** de autoridade: vence o que a SEFIN vai ler.
    """
    return _gerar_pfx(
        cn="EMPRESA CONFUSA LTDA:11222333000181",
        cnpj_no_org_id="11444777000161",
        cnpj_no_othername="12345678000195",
    )


@pytest.fixture(scope="session")
def pfx_e_cpf() -> PfxGerado:
    """e-CPF: `otherName` com OID 2.16.76.1.3.1 e nenhum CNPJ."""
    return _gerar_pfx(
        cn="FULANO DE TAL:12345678909",
        cpf_no_othername="19000101123456789012345678909000000000000000000000000000",
    )


@pytest.fixture(scope="session")
def pfx_sem_identificacao() -> PfxGerado:
    """Nem CNPJ nem CPF em lugar nenhum."""
    return _gerar_pfx(cn="CERTIFICADO ANONIMO")


@pytest.fixture(scope="session")
def pfx_org_id_discorda_do_cn() -> PfxGerado:
    """Sem `otherName`: `2.5.4.97` e `CN` trazem CNPJs diferentes.

    Separa a segunda da terceira fonte. Sem ele, trocar a ordem entre as duas não quebra
    teste nenhum — o `otherName` do certificado de três fontes decide antes.
    """
    return _gerar_pfx(cn="EMPRESA LTDA:11222333000181", cnpj_no_org_id="12345678000195")


@pytest.fixture(scope="session")
def pfx_othername_octet_string() -> PfxGerado:
    """O mesmo CNPJ no `otherName`, mas embrulhado em `OCTET STRING` em vez de
    `PrintableString`.

    O tipo de string varia entre emissores, e uma implementação que reconhecesse só um
    dos dois tags passaria despercebida enquanto as fixtures gerassem só esse.
    """
    return _gerar_pfx(
        cn="EMPRESA OCTET LTDA",
        cnpj_no_othername="12345678000195",
        tag_othername=TAG_OCTET_STRING,
    )
