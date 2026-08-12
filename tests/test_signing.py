"""Testes de `nfse_sefin.signing` e `nfse_sefin.perfis`.

Assinatura é onde erro silencioso mora: o documento sai bem formado, a requisição sai,
e só o servidor sabe que o digest não bate — devolvendo um código que não diz isso.

Por isso estes testes não param em "assinou". Eles conferem a forma exigida pelo XSD,
validam a assinatura contra os dois `xmldsig-core-schema.xsd` oficiais, e provam que a
assinatura sobrevive ao caminho de transporte inteiro.
"""

from __future__ import annotations

from pathlib import Path

import nfelib
import pytest
from lxml import etree

from nfse_sefin.cert import Certificate
from nfse_sefin.perfis import (
    ALG_C14N,
    ALG_ENVELOPED,
    NS_XMLDSIG,
    PERFIL_100,
    PERFIL_101,
    PERFIL_PADRAO,
    PERFIS,
    Perfil,
    por_nome,
)
from nfse_sefin.signing import (
    NS_NFSE,
    AssinaturaError,
    assinar,
    verificar,
)
from nfse_sefin.transport import de_gzip_b64, gzip_b64
from tests.conftest import PfxGerado

SCHEMAS = Path(__file__).resolve().parent.parent / "Schemas"
AMOSTRA = Path(nfelib.__file__).resolve().parent / "nfse" / "samples" / "v1_0" / "dps-simples.xml"


@pytest.fixture(scope="module")
def dps_xml() -> bytes:
    return AMOSTRA.read_bytes()


@pytest.fixture(scope="module")
def certificado(pfx_valido: PfxGerado) -> Certificate:
    return Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)


def _assinatura(xml: bytes) -> etree._Element:
    elemento = etree.fromstring(xml).find(f"{{{NS_XMLDSIG}}}Signature")
    assert elemento is not None, "documento sem <Signature>"
    return elemento


# ------------------------------------------------------------------- perfis


def test_os_dois_perfis_do_eixo() -> None:
    assert PERFIS == (PERFIL_100, PERFIL_101)
    assert PERFIL_100.versao == "1.00" and PERFIL_100.hash_hashlib == "sha1"
    assert PERFIL_101.versao == "1.01" and PERFIL_101.hash_hashlib == "sha256"


def test_perfil_padrao_e_o_com_evidencia_em_producao() -> None:
    """Enquanto o probe não roda, o padrão é o par que uma lib MIT usa hoje."""
    assert PERFIL_PADRAO is PERFIL_100


@pytest.mark.parametrize("chave", ["1.00+SHA1", "1.00", "1.01+SHA256", "1.01"])
def test_por_nome_aceita_rotulo_e_versao(chave: str) -> None:
    assert por_nome(chave) in PERFIS


def test_por_nome_desconhecido_lista_os_validos() -> None:
    with pytest.raises(ValueError, match="1.00\\+SHA1"):
        por_nome("2.00")


def test_so_o_hash_varia_entre_perfis() -> None:
    """Canonicalização e transforms são iguais nos dois — só o par de hash difere.

    A forma estrita da 1.00 vale sob os dois schemas, então não há motivo para variar
    mais nada, e variar aumentaria a matriz de coisas que podem estar erradas.
    """
    assert PERFIL_100.algoritmo_assinatura != PERFIL_101.algoritmo_assinatura
    assert PERFIL_100.algoritmo_digest != PERFIL_101.algoritmo_digest
    assert PERFIL_100.hash_hashlib != PERFIL_101.hash_hashlib


def test_perfil_e_imutavel() -> None:
    with pytest.raises(AttributeError):
        PERFIL_100.versao = "9.99"  # type: ignore[misc]


# ------------------------------------------------------------------ assinar


@pytest.mark.parametrize("perfil", PERFIS, ids=lambda p: p.nome)
def test_assina_e_verifica(dps_xml: bytes, certificado: Certificate, perfil: Perfil) -> None:
    assert verificar(assinar(dps_xml, certificado, perfil), perfil)


@pytest.mark.parametrize("perfil", PERFIS, ids=lambda p: p.nome)
def test_assinatura_sobrevive_ao_transporte(
    dps_xml: bytes, certificado: Certificate, perfil: Perfil
) -> None:
    """Assinar → gzip → base64 → decodificar → descomprimir → verificar.

    O caminho completo, porque o byte assinado tem de ser o byte enviado. Qualquer
    reserialização no meio reordena namespace ou mexe em espaço em branco, o digest
    para de bater, e a rejeição não diz que foi isso.
    """
    assinado = assinar(dps_xml, certificado, perfil)

    ida_e_volta = de_gzip_b64(gzip_b64(assinado))

    assert ida_e_volta == assinado
    assert verificar(ida_e_volta, perfil)


@pytest.mark.parametrize("perfil", PERFIS, ids=lambda p: p.nome)
def test_forma_exigida_pelo_xsd(dps_xml: bytes, certificado: Certificate, perfil: Perfil) -> None:
    """Exatamente dois transforms, na ordem certa, e `KeyInfo` presente.

    O XSD 1.00 fixa `minOccurs=2 maxOccurs=2` nos transforms e torna `KeyInfo`
    obrigatório. Emitir assim vale para os dois schemas.
    """
    assinatura = _assinatura(assinar(dps_xml, certificado, perfil))

    transforms = assinatura.findall(f".//{{{NS_XMLDSIG}}}Transform")
    assert [t.get("Algorithm") for t in transforms] == [ALG_ENVELOPED, ALG_C14N]

    c14n = assinatura.find(f".//{{{NS_XMLDSIG}}}CanonicalizationMethod")
    assert c14n is not None and c14n.get("Algorithm") == ALG_C14N

    certificado_embutido = assinatura.findtext(
        f"{{{NS_XMLDSIG}}}KeyInfo/{{{NS_XMLDSIG}}}X509Data/{{{NS_XMLDSIG}}}X509Certificate"
    )
    assert certificado_embutido


@pytest.mark.parametrize("perfil", PERFIS, ids=lambda p: p.nome)
def test_algoritmos_vem_do_perfil(dps_xml: bytes, certificado: Certificate, perfil: Perfil) -> None:
    """Nunca hardcoded — é o eixo inteiro do Approach C."""
    assinatura = _assinatura(assinar(dps_xml, certificado, perfil))

    metodo = assinatura.find(f".//{{{NS_XMLDSIG}}}SignatureMethod")
    digest = assinatura.find(f".//{{{NS_XMLDSIG}}}DigestMethod")
    assert metodo is not None and metodo.get("Algorithm") == perfil.algoritmo_assinatura
    assert digest is not None and digest.get("Algorithm") == perfil.algoritmo_digest


def test_signature_e_irma_do_infdps_e_a_ultima(dps_xml: bytes, certificado: Certificate) -> None:
    raiz = etree.fromstring(assinar(dps_xml, certificado))
    filhos = list(raiz)

    assert filhos[0].tag == f"{{{NS_NFSE}}}infDPS"
    assert filhos[-1].tag == f"{{{NS_XMLDSIG}}}Signature"


def test_referencia_aponta_para_o_id_do_infdps(dps_xml: bytes, certificado: Certificate) -> None:
    assinado = assinar(dps_xml, certificado)
    raiz = etree.fromstring(assinado)

    identificador = raiz.find(f"{{{NS_NFSE}}}infDPS").get("Id")  # type: ignore[union-attr]
    referencia = _assinatura(assinado).find(f".//{{{NS_XMLDSIG}}}Reference")

    assert referencia is not None
    assert referencia.get("URI") == f"#{identificador}"


# ------------------------------------------------- regras de recepção


@pytest.mark.parametrize("perfil", PERFIS, ids=lambda p: p.nome)
def test_sem_prefixo_de_namespace(dps_xml: bytes, certificado: Certificate, perfil: Perfil) -> None:
    """E1228. A `Signature` mora noutro namespace e ainda assim não pode usar `ds:`."""
    assinado = assinar(dps_xml, certificado, perfil)

    assert b"ns0:" not in assinado
    assert b"ds:" not in assinado
    for elemento in etree.fromstring(assinado).iter():
        assert elemento.prefix is None, f"{elemento.tag} saiu com prefixo"


@pytest.mark.parametrize("perfil", PERFIS, ids=lambda p: p.nome)
def test_saida_e_utf8(dps_xml: bytes, certificado: Certificate, perfil: Perfil) -> None:
    """E1229."""
    assinado = assinar(dps_xml, certificado, perfil)
    assert b"UTF-8" in assinado[:60]
    assinado.decode("utf-8")


def test_sem_declaracao_de_namespace_vazia(dps_xml: bytes, certificado: Certificate) -> None:
    """Guarda o **sintoma** do bug de montar o `SignedInfo` solto e anexar depois.

    A invariante de verdade — o byte assinado é o byte enviado — é guardada por
    `test_assina_e_verifica` e `test_assinatura_sobrevive_ao_transporte`: quebrá-la
    derruba cinco testes. Este aqui é mais estreito de propósito, porque `xmlns=""` na
    saída é defeito seja qual for a causa.

    Mover subárvore entre árvores fazia o `lxml` emitir `xmlns=""` em `Transforms`, o
    `SignedInfo` canonicalizado na hora de assinar deixava de bater com o serializado,
    e a verificação falhava. Construir no lugar elimina a classe inteira.
    """
    assert b'xmlns=""' not in assinar(dps_xml, certificado)


# ------------------------------------------- validação contra os XSD oficiais


def test_perfil_estrito_valida_sob_os_dois_schemas(
    dps_xml: bytes, certificado: Certificate
) -> None:
    """A tese que decide `signing.py`, verificada e não suposta.

    O `xmldsig-core-schema.xsd` da 1.00 é a variante restrita do governo, que fixa
    `rsa-sha1`. O da 1.01 é o W3C genérico. Assinar na forma estrita vale nos dois.
    """
    assinatura = _assinatura(assinar(dps_xml, certificado, PERFIL_100))
    avulsa = etree.fromstring(etree.tostring(assinatura))

    for versao in ("1.00", "1.01"):
        schema = etree.XMLSchema(etree.parse(str(SCHEMAS / versao / "xmldsig-core-schema.xsd")))
        assert schema.validate(avulsa), f"não validou sob {versao}: {schema.error_log}"


def test_sha256_e_recusado_pelo_schema_restrito(dps_xml: bytes, certificado: Certificate) -> None:
    """O outro lado da mesma moeda, e a razão de o eixo existir.

    A 1.00 fixa `rsa-sha1` com `fixed=`, então o perfil SHA-256 é inválido sob ela.
    Se um ZIP futuro afrouxar isso, este teste falha e o eixo pode encolher.
    """
    assinatura = _assinatura(assinar(dps_xml, certificado, PERFIL_101))
    avulsa = etree.fromstring(etree.tostring(assinatura))

    restrito = etree.XMLSchema(etree.parse(str(SCHEMAS / "1.00" / "xmldsig-core-schema.xsd")))
    generico = etree.XMLSchema(etree.parse(str(SCHEMAS / "1.01" / "xmldsig-core-schema.xsd")))

    assert not restrito.validate(avulsa)
    assert generico.validate(avulsa)


def test_dps_assinada_valida_contra_o_xsd_da_dps(dps_xml: bytes, certificado: Certificate) -> None:
    """O documento inteiro, não só a assinatura.

    Só sob a 1.00: o `TSSerieDPS` da 1.01 publicada tem `pattern` com `^` e `$`
    literais e rejeita qualquer série real. Ver a seção do defeito no `DESIGN.md`.
    """
    schema = etree.XMLSchema(etree.parse(str(SCHEMAS / "1.00" / "DPS_v1.00.xsd")))

    documento = etree.fromstring(assinar(dps_xml, certificado, PERFIL_100))

    assert schema.validate(documento), schema.error_log


# ----------------------------------------------------------- adulteração


def test_alterar_o_infdps_invalida(dps_xml: bytes, certificado: Certificate) -> None:
    assinado = assinar(dps_xml, certificado)
    raiz = etree.fromstring(assinado)
    raiz.find(f"{{{NS_NFSE}}}infDPS/{{{NS_NFSE}}}serie").text = "999"  # type: ignore[union-attr]

    assert not verificar(etree.tostring(raiz), PERFIL_100)


def test_alterar_a_assinatura_invalida(dps_xml: bytes, certificado: Certificate) -> None:
    assinado = assinar(dps_xml, certificado)
    raiz = etree.fromstring(assinado)
    valor = raiz.find(f"{{{NS_XMLDSIG}}}Signature/{{{NS_XMLDSIG}}}SignatureValue")
    assert valor is not None and valor.text
    valor.text = "A" + valor.text[1:] if valor.text[0] != "A" else "B" + valor.text[1:]

    assert not verificar(etree.tostring(raiz), PERFIL_100)


def test_verificar_com_o_perfil_errado_falha(dps_xml: bytes, certificado: Certificate) -> None:
    """Assinado com SHA-1, conferido como SHA-256: o digest nem chega a bater."""
    assinado = assinar(dps_xml, certificado, PERFIL_100)
    assert not verificar(assinado, PERFIL_101)


def test_documento_sem_assinatura_nao_verifica(dps_xml: bytes) -> None:
    assert not verificar(dps_xml)


# ------------------------------------------------------------------ erros


def test_xml_malformado(certificado: Certificate) -> None:
    with pytest.raises(AssinaturaError, match="inválido"):
        assinar(b"<DPS><nao fecha>", certificado)


def test_sem_elemento_assinavel(certificado: Certificate) -> None:
    with pytest.raises(AssinaturaError, match="assinável"):
        assinar(b'<DPS xmlns="http://www.sped.fazenda.gov.br/nfse"><outro/></DPS>', certificado)


def test_elemento_assinavel_sem_id(certificado: Certificate) -> None:
    xml = b'<DPS xmlns="http://www.sped.fazenda.gov.br/nfse"><infDPS><a>1</a></infDPS></DPS>'
    with pytest.raises(AssinaturaError, match="`Id`"):
        assinar(xml, certificado)


def test_assina_pedido_de_evento(certificado: Certificate) -> None:
    """O mesmo assinador serve `infPedReg` e `infEvento`, não só `infDPS`."""
    xml = (
        b'<pedRegEvento xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
        b'<infPedReg Id="PRE123"><tpAmb>2</tpAmb></infPedReg></pedRegEvento>'
    )

    assinado = assinar(xml, certificado)

    assert verificar(assinado, PERFIL_100)
    referencia = _assinatura(assinado).find(f".//{{{NS_XMLDSIG}}}Reference")
    assert referencia is not None and referencia.get("URI") == "#PRE123"
