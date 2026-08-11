"""Teste de contrato com a `nfelib`.

Esta biblioteca não escreve os 416 campos do leiaute à mão: ela usa os bindings que
a `nfelib` gera com `xsdata` a partir dos XSD oficiais. Isso é barato, e o preço é
uma dependência de forma: se o upstream regenerar os bindings, renomear um campo ou
publicar um esquema novo, o mapeamento quebra em silêncio.

Este arquivo é o alarme. Ele falha ruidosamente quando qualquer coisa em que o
`adapters/` se apoia muda de forma.

Também trava as duas regras de recepção que rejeitam na primeira requisição e são
fáceis de não notar até tomar o erro em produção:

- **E1228** — `RN_RECEPCAO_DPS` #14: prefixo de namespace na área de dados
  descompactada é proibido. O serializer padrão do `xsdata` emite `ns0:`.
- **E1229** — `RN_RECEPCAO_DPS` #15: o XML tem de ser UTF-8.
"""

from __future__ import annotations

import re
from importlib.metadata import version
from pathlib import Path

import pytest
from lxml import etree
from nfelib.nfse.bindings.v1_0.dps_v1_00 import Dps
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

NAMESPACE_NFSE = "http://www.sped.fazenda.gov.br/nfse"

# Pin exato declarado no pyproject. Ver OQ10 no DESIGN.md: afrouxar para faixa só
# depois que esta suíte estiver madura.
NFELIB_PIN = "2.5.2"

SCHEMAS = Path(__file__).resolve().parent.parent / "Schemas"


def _sample_path(nome: str) -> Path:
    import nfelib

    return Path(nfelib.__file__).resolve().parent / "nfse" / "samples" / "v1_0" / nome


def _serializar(dps: Dps) -> str:
    """Serializa uma DPS na forma que a SEFIN aceita.

    O `ns_map={None: ...}` não é cosmético: sem ele o `xsdata` emite `ns0:` em cada
    elemento e a recepção rejeita com E1228. É a razão de `adapters/` ser o único
    lugar autorizado a serializar.
    """
    config = SerializerConfig(indent=None, xml_declaration=True, encoding="UTF-8")
    return XmlSerializer(config=config).render(dps, ns_map={None: NAMESPACE_NFSE})


@pytest.fixture(scope="module")
def dps_exemplo() -> Dps:
    xml = _sample_path("dps-simples.xml").read_text(encoding="utf-8")
    return XmlParser().from_string(xml, Dps)


def test_nfelib_esta_no_pin_exato() -> None:
    """Falha quando alguém afrouxa o pin sem passar por esta suíte."""
    assert version("nfelib") == NFELIB_PIN


def test_samples_da_nfelib_continuam_existindo() -> None:
    """`adapters/` e esta suíte usam os samples do upstream como fixture."""
    for nome in ("dps-simples.xml", "dps-regime-normal.xml"):
        assert _sample_path(nome).is_file(), f"sample {nome} sumiu da nfelib"


def test_caminhos_que_a_fachada_mapeia(dps_exemplo: Dps) -> None:
    """Trava os caminhos exatos que `adapters/nfelib.py` traduz.

    Os bindings preservam os nomes do XSD, então é `infDPS`, não `inf_dps`. Um
    `xsdata` novo com outra política de nomes quebraria aqui, e não em produção.
    """
    inf = dps_exemplo.infDPS
    assert inf is not None

    assert dps_exemplo.versao == "1.00"
    assert inf.Id == "DPS140015920176113500013200900000000000000006"

    # O caminho que o dev de petshop nunca deveria precisar conhecer.
    assert inf.serv is not None
    assert inf.serv.cServ is not None
    assert inf.serv.cServ.cTribNac == "010101"

    assert inf.prest is not None
    assert inf.prest.CNPJ == "01761135000132"


def test_ctribnac_tem_seis_digitos(dps_exemplo: Dps) -> None:
    """P5: o campo real é `cTribNac`, 6 dígitos numéricos — não "01.01".

    O leiaute exportado do Excel perdeu zeros à esquerda em cerca de um terço da
    lista de serviços (OQ5). O sample oficial é a referência de forma.
    """
    assert dps_exemplo.infDPS is not None
    assert dps_exemplo.infDPS.serv is not None
    assert dps_exemplo.infDPS.serv.cServ is not None
    codigo = dps_exemplo.infDPS.serv.cServ.cTribNac
    assert codigo is not None
    assert len(codigo) == 6
    assert codigo.isdigit()


def test_dcompet_e_data_completa(dps_exemplo: Dps) -> None:
    """P5: `dCompet` é tipo D (AAAA-MM-DD), não competência AAAA-MM."""
    assert dps_exemplo.infDPS is not None
    competencia = dps_exemplo.infDPS.dCompet
    assert competencia is not None
    assert len(str(competencia)) == len("AAAA-MM-DD")
    etree.fromstring(f"<d>{competencia}</d>".encode())  # sanidade: sem lixo


def test_round_trip_preserva_o_objeto(dps_exemplo: Dps) -> None:
    """Parse -> serialize -> parse tem de devolver a mesma árvore.

    Perda silenciosa aqui significa campo que some entre o que o chamador montou e
    o que a SEFIN recebe.
    """
    reparsed = XmlParser().from_string(_serializar(dps_exemplo), Dps)
    assert reparsed == dps_exemplo


def test_saida_nao_tem_prefixo_de_namespace(dps_exemplo: Dps) -> None:
    """E1228 — `RN_RECEPCAO_DPS` #14.

    Chamar o serializer do `xsdata` sem `ns_map` produz `ns0:DPS`, `ns0:infDPS`, e a
    recepção rejeita. Este teste é a única coisa que impede a regressão.
    """
    xml = _serializar(dps_exemplo)

    # Casa qualquer prefixo, não só `ns0`. Um serializer futuro que escolhesse
    # `nfse:` seria igualmente rejeitado pela recepção, e um teste que procura a
    # string literal "ns0:" deixaria passar.
    prefixado = re.search(r"<[A-Za-z_][\w.-]*:", xml)
    assert prefixado is None, f"saída tem prefixo de namespace: {prefixado!r}"

    raiz = etree.fromstring(xml.encode("utf-8"))
    assert raiz.tag == f"{{{NAMESPACE_NFSE}}}DPS"
    # Sem guarda de `isinstance`: o serializer do xsdata não emite comentário nem
    # processing instruction, então `.tag` é sempre `str` aqui — e é assim que o
    # lxml-stubs tipa, então a guarda seria código morto sob `mypy --strict`.
    for elemento in raiz.iter():
        assert elemento.tag.startswith(f"{{{NAMESPACE_NFSE}}}"), f"{elemento.tag} fora do namespace"


def test_serializer_padrao_realmente_emite_prefixo(dps_exemplo: Dps) -> None:
    """Prova que o teste acima guarda algo real, e não uma condição vazia.

    Se um `xsdata` futuro passar a omitir o prefixo por conta própria, este teste
    falha e nos avisa que a proteção do `_serializar` virou redundante — o que é uma
    informação útil, não um problema.
    """
    config = SerializerConfig(indent=None, xml_declaration=True, encoding="UTF-8")
    ingenuo = XmlSerializer(config=config).render(dps_exemplo)
    assert "ns0:" in ingenuo


def test_saida_e_utf8(dps_exemplo: Dps) -> None:
    """E1229 — `RN_RECEPCAO_DPS` #15."""
    xml = _serializar(dps_exemplo)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert xml.encode("utf-8").decode("utf-8") == xml


@pytest.mark.parametrize("sample", ["dps-simples.xml", "dps-regime-normal.xml"])
def test_valida_contra_xsd_oficial_vendorizado(sample: str) -> None:
    """O XML que sai daqui valida contra o XSD oficial, não contra a cópia da nfelib.

    A `nfelib` 2.5.2 embarca esquemas 1.00 mais antigos que o ZIP publicado. Ver
    `Schemas/PROCEDENCIA.md`.
    """
    schema = etree.XMLSchema(etree.parse(str(SCHEMAS / "1.00" / "DPS_v1.00.xsd")))
    dps = XmlParser().from_string(_sample_path(sample).read_text(encoding="utf-8"), Dps)

    documento = etree.fromstring(_serializar(dps).encode("utf-8"))

    assert schema.validate(documento), schema.error_log


def test_esquemas_das_duas_versoes_estao_vendorizados() -> None:
    """`perfis.py` (Approach C) precisa dos dois lados do eixo em disco."""
    for versao, dps_xsd in (("1.00", "DPS_v1.00.xsd"), ("1.01", "DPS_v1.01.xsd")):
        assert (SCHEMAS / versao / dps_xsd).is_file()
        assert (SCHEMAS / versao / "xmldsig-core-schema.xsd").is_file()


def test_xmldsig_diverge_entre_as_versoes() -> None:
    """OQ4, e é o achado que decide `signing.py`.

    A 1.00 traz a variante restrita do governo, que fixa rsa-sha1, sha1, exatamente
    dois transforms e `KeyInfo` obrigatório. A 1.01 volta ao W3C genérico, sem
    restrição. Assinar na forma estrita da 1.00 valida sob as duas — e é por isso
    que `signing.py` varia só o hash.

    Se um ZIP futuro unificar os dois, este teste falha e o eixo de perfil pode
    encolher para uma constante.
    """
    restrito = (SCHEMAS / "1.00" / "xmldsig-core-schema.xsd").read_text(encoding="utf-8")
    generico = (SCHEMAS / "1.01" / "xmldsig-core-schema.xsd").read_text(encoding="utf-8")

    assert restrito != generico
    assert 'fixed="http://www.w3.org/2000/09/xmldsig#rsa-sha1"' in restrito
    assert 'fixed="http://www.w3.org/2000/09/xmldsig#sha1"' in restrito
    assert "rsa-sha1" not in generico
