"""Testes do adapter — a única fronteira com a `nfelib`.

Três coisas se provam aqui, e nenhuma é opinião:

1. O XML sai **sem prefixo de namespace** (E1228) e em **UTF-8** (E1229). São as duas
   regras de `RN_RECEPCAO_DPS` que rejeitam na primeira requisição.
2. O documento **valida contra o XSD oficial da 1.00**, antes e depois de assinado.
3. O que a fachada montou chega inteiro ao XML — nenhum campo some no caminho.

O quarto ponto, que não tem teste próprio porque é um teste de todos os outros: o
adapter serializa **uma vez**. `test_signing.py` guarda o que acontece quando algo
reserializa depois da assinatura.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from nfse_sefin.adapters.nfelib import NAMESPACE, construir, serializar
from nfse_sefin.ambientes import Ambiente
from nfse_sefin.cert import Certificate
from nfse_sefin.errors import DadosInvalidosError
from nfse_sefin.facade import (
    DPS,
    Endereco,
    OpcaoSimplesNacional,
    Prestador,
    RegimeApuracaoSN,
    RegimeEspecial,
    Servico,
    Tomador,
    TotalTributos,
)
from nfse_sefin.perfis import PERFIL_100, PERFIL_101, Perfil
from nfse_sefin.signing import assinar, verificar
from nfse_sefin.transport import gzip_b64

RAIZ = Path(__file__).resolve().parent.parent
SCHEMAS = RAIZ / "Schemas"
FUSO_BR = timezone(timedelta(hours=-3))

CNPJ = "01761135000132"
CPF = "11144477735"
MUNICIPIO = "1400159"
ID_ESPERADO = "DPS140015920176113500013200900000000000000006"


def _dps_mei() -> DPS:
    return DPS(
        prestador=Prestador(
            cnpj=CNPJ,
            inscricao_municipal=CNPJ,
            simples_nacional=OpcaoSimplesNacional.MEI,
        ),
        servico=Servico(
            codigo="010101",
            descricao="Banho e tosa",
            valor=Decimal("150.00"),
            municipio_prestacao=MUNICIPIO,
        ),
        serie="900",
        numero="6",
        competencia=date(2022, 9, 28),
        municipio_emissor=MUNICIPIO,
        emitido_em=datetime(2022, 9, 28, 13, 50, 29, tzinfo=FUSO_BR),
    )


def _dps_completa() -> DPS:
    """Todo campo opcional que a fachada conhece, preenchido."""
    return DPS(
        prestador=Prestador(
            cnpj=CNPJ,
            inscricao_municipal="12345",
            nome="Petshop Exemplo Ltda",
            telefone="(69) 3222-1234",
            email="contato@petshop.com.br",
            endereco=Endereco(
                "Avenida Sete de Setembro",
                "1200",
                "Centro",
                MUNICIPIO,
                "76801-000",
                complemento="Sala 3",
            ),
            simples_nacional=OpcaoSimplesNacional.ME_EPP,
            regime_apuracao_sn=RegimeApuracaoSN.FEDERAIS_E_MUNICIPAL_PELO_SN,
            regime_especial=RegimeEspecial.SOCIEDADE_DE_PROFISSIONAIS,
        ),
        servico=Servico(
            codigo="010101",
            descricao="Banho, tosa e hidratação",
            valor=Decimal("150.00"),
            municipio_prestacao=MUNICIPIO,
            aliquota=Decimal("5"),
            codigo_municipal="101",
            codigo_interno="PED42",
            informacoes_complementares="Contrato 2026/08",
            total_tributos=TotalTributos.pelo_simples_nacional("6.00"),
        ),
        tomador=Tomador(
            cpf=CPF,
            nome="Fulano de Tal",
            endereco=Endereco("Rua B", "20", "Bairro Novo", MUNICIPIO, "76802-000"),
        ),
        serie="900",
        numero="6",
        competencia=date(2022, 9, 28),
        municipio_emissor=MUNICIPIO,
        emitido_em=datetime(2022, 9, 28, 13, 50, 29, tzinfo=FUSO_BR),
        ambiente=Ambiente.PRODUCAO,
    )


@pytest.fixture(scope="module")
def schema_100() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(SCHEMAS / "1.00" / "DPS_v1.00.xsd")))


def _texto(documento: etree._Element, caminho: str) -> str | None:
    elemento = documento.find(caminho, namespaces={"n": NAMESPACE})
    return None if elemento is None else elemento.text


# ------------------------------------------------------- as duas regras de recepção


@pytest.mark.parametrize("montar", [_dps_mei, _dps_completa])
def test_saida_nao_tem_prefixo_de_namespace(montar: object) -> None:
    """E1228 — `RN_RECEPCAO_DPS` #14.

    Sem `ns_map={None: NAMESPACE}` o `xsdata` emite `ns0:DPS` e a recepção rejeita
    antes de olhar o conteúdo. O `re` casa qualquer prefixo, não só `ns0`: um
    serializer futuro que escolhesse `nfse:` seria igualmente rejeitado.
    """
    xml = serializar(montar()).decode("utf-8")  # type: ignore[operator]

    prefixado = re.search(r"<[A-Za-z_][\w.-]*:", xml)
    assert prefixado is None, f"saída tem prefixo de namespace: {prefixado!r}"

    raiz = etree.fromstring(xml.encode("utf-8"))
    for elemento in raiz.iter():
        assert elemento.tag.startswith(f"{{{NAMESPACE}}}"), f"{elemento.tag} fora do namespace"


def test_saida_e_utf8_com_declaracao() -> None:
    """E1229 — `RN_RECEPCAO_DPS` #15."""
    xml = serializar(_dps_mei())

    assert xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert xml.decode("utf-8").encode("utf-8") == xml


def test_serializar_devolve_bytes() -> None:
    """Bytes, não `str`: é o que `signing.assinar` e `gzip_b64` consomem.

    Devolver `str` obrigaria cada chamador a escolher um encoding, e a escolha errada
    é E1229.
    """
    assert isinstance(serializar(_dps_mei()), bytes)


# ------------------------------------------------------------- validação contra XSD


@pytest.mark.parametrize("montar", [_dps_mei, _dps_completa])
def test_valida_contra_o_xsd_oficial_100(montar: object, schema_100: etree.XMLSchema) -> None:
    """O XSD do ZIP publicado, não a cópia mais antiga que a `nfelib` embarca."""
    documento = etree.fromstring(serializar(montar()))  # type: ignore[operator]
    assert schema_100.validate(documento), schema_100.error_log


@pytest.mark.parametrize(
    "total",
    [
        TotalTributos.nao_informar(),
        TotalTributos.pelo_simples_nacional("6.00"),
        TotalTributos.por_valor("10.50", "0", "5"),
        TotalTributos.por_percentual("1.5", "0", "5"),
    ],
)
def test_todos_os_ramos_do_tottrib_validam(
    total: TotalTributos, schema_100: etree.XMLSchema
) -> None:
    """`totTrib` é um `xs:choice` de quatro, e os quatro precisam sair bem formados.

    O regime aqui é sempre o que permite o ramo — a matriz de compatibilidade tem
    teste próprio em `test_facade.py`.
    """
    regime = {
        "indTotTrib": OpcaoSimplesNacional.MEI,
        "pTotTribSN": OpcaoSimplesNacional.ME_EPP,
        "vTotTrib": OpcaoSimplesNacional.NAO_OPTANTE,
        "pTotTrib": OpcaoSimplesNacional.NAO_OPTANTE,
    }[total.ramo]

    documento = etree.fromstring(
        serializar(
            DPS(
                prestador=Prestador(cnpj=CNPJ, simples_nacional=regime),
                servico=Servico(
                    codigo="010101",
                    descricao="X",
                    valor=Decimal("150.00"),
                    municipio_prestacao=MUNICIPIO,
                    total_tributos=total,
                ),
                serie="1",
                numero="1",
                competencia=date(2026, 8, 17),
                municipio_emissor=MUNICIPIO,
                emitido_em=datetime(2026, 8, 17, 10, 0, tzinfo=FUSO_BR),
            )
        )
    )
    assert schema_100.validate(documento), schema_100.error_log


def test_o_xsd_101_publicado_recusa_qualquer_serie() -> None:
    """O defeito conhecido da 1.01, travado como fato em vez de nota de rodapé.

    `TSSerieDPS` traz `pattern="^0{0,4}\\d{1,5}$"`, e em XML Schema `^` e `$` são
    caracteres literais — o padrão já é ancorado. Resultado: nenhuma série real
    valida, e portanto **nenhuma DPS** valida contra o `Schemas/1.01/`.

    Isso não é motivo para abandonar o perfil 1.01: o `pynfse-nacional` emite
    `versao="1.01"` em produção e afirma funcionar, o que significa que o XSD
    publicado não é o que a SEFIN aplica. Quando um ZIP novo corrigir o padrão, este
    teste falha e avisa que o perfil 1.01 passou a ser validável localmente.
    """
    schema = etree.XMLSchema(etree.parse(str(SCHEMAS / "1.01" / "DPS_v1.01.xsd")))
    documento = etree.fromstring(serializar(_dps_mei(), PERFIL_101))

    assert not schema.validate(documento)
    erros = str(schema.error_log)
    assert "serie" in erros
    # E só isso: se aparecer outro campo, o problema deixou de ser só o padrão da série.
    assert erros.count("SCHEMAV_CVC") == 1, erros


# ------------------------------------------------------- o que a fachada montou chega


def test_campos_obrigatorios_chegam_ao_xml() -> None:
    documento = etree.fromstring(serializar(_dps_mei()))
    inf = documento.find(f"{{{NAMESPACE}}}infDPS")
    assert inf is not None

    assert inf.get("Id") == ID_ESPERADO
    assert documento.get("versao") == "1.00"
    assert _texto(inf, f"{{{NAMESPACE}}}tpAmb") == "2"
    assert _texto(inf, f"{{{NAMESPACE}}}dhEmi") == "2022-09-28T13:50:29-03:00"
    assert _texto(inf, f"{{{NAMESPACE}}}serie") == "900"
    assert _texto(inf, f"{{{NAMESPACE}}}nDPS") == "6"
    assert _texto(inf, f"{{{NAMESPACE}}}dCompet") == "2022-09-28"
    assert _texto(inf, f"{{{NAMESPACE}}}tpEmit") == "1"
    assert _texto(inf, f"{{{NAMESPACE}}}cLocEmi") == MUNICIPIO


def test_o_caminho_que_o_dev_nunca_ve() -> None:
    """`Servico(codigo="010101")` de um lado, `serv/cServ/cTribNac` do outro.

    É a promessa do projeto em uma asserção.
    """
    documento = etree.fromstring(serializar(_dps_mei()))
    caminho = (
        f"{{{NAMESPACE}}}infDPS/{{{NAMESPACE}}}serv/{{{NAMESPACE}}}cServ/{{{NAMESPACE}}}cTribNac"
    )
    assert _texto(documento, caminho) == "010101"


def test_campos_opcionais_chegam_ao_xml() -> None:
    """Se um opcional some no caminho, ninguém percebe até a nota sair errada."""
    xml = serializar(_dps_completa()).decode("utf-8")

    for esperado in (
        "<xNome>Petshop Exemplo Ltda</xNome>",
        "<fone>6932221234</fone>",
        "<email>contato@petshop.com.br</email>",
        "<xLgr>Avenida Sete de Setembro</xLgr>",
        "<xCpl>Sala 3</xCpl>",
        "<CEP>76801000</CEP>",
        "<regApTribSN>1</regApTribSN>",
        "<regEspTrib>6</regEspTrib>",
        "<cTribMun>101</cTribMun>",
        "<cIntContrib>PED42</cIntContrib>",
        "<xInfComp>Contrato 2026/08</xInfComp>",
        "<pAliq>5.00</pAliq>",
        "<pTotTribSN>6.00</pTotTribSN>",
        "<xNome>Fulano de Tal</xNome>",
        f"<CPF>{CPF}</CPF>",
        "<tpAmb>1</tpAmb>",
    ):
        assert esperado in xml, f"sumiu no caminho: {esperado}"


def test_ausente_na_fachada_nao_aparece_no_xml() -> None:
    """Campo vazio emitido como elemento vazio é rejeição de schema."""
    xml = serializar(_dps_mei()).decode("utf-8")

    for indesejado in ("<xNome", "<fone", "<email", "<end>", "<toma>", "<pAliq", "<cTribMun"):
        assert indesejado not in xml, f"apareceu sem ter sido informado: {indesejado}"


def test_valor_sai_com_duas_casas() -> None:
    """`TSDec15V2` recusa `150.5` e recusa `0150.00`. `:.2f` acerta os dois."""
    documento = _dps_mei()
    xml = serializar(documento).decode("utf-8")
    assert "<vServ>150.00</vServ>" in xml


def test_valor_zero_sai_no_formato_do_padrao() -> None:
    """O padrão aceita `0` e `0.00`, e recusa `.00`."""
    documento = DPS(
        prestador=Prestador(cnpj=CNPJ, simples_nacional=OpcaoSimplesNacional.NAO_OPTANTE),
        servico=Servico(
            codigo="010101",
            descricao="Cortesia",
            valor=Decimal("0"),
            municipio_prestacao=MUNICIPIO,
            total_tributos=TotalTributos.por_valor("0", "0", "0"),
        ),
        serie="1",
        numero="1",
        competencia=date(2026, 8, 17),
        municipio_emissor=MUNICIPIO,
        emitido_em=datetime(2026, 8, 17, 10, 0, tzinfo=FUSO_BR),
    )
    assert "<vServ>0.00</vServ>" in serializar(documento).decode("utf-8")


# ------------------------------------------------------------------- o eixo de perfil


def test_perfil_decide_o_atributo_versao() -> None:
    """Approach C: mesma árvore, `versao` diferente. É o que o eixo significa."""
    assert construir(_dps_mei(), PERFIL_100).versao == "1.00"
    assert construir(_dps_mei(), PERFIL_101).versao == "1.01"


def test_regime_especial_outros_e_recusado_na_100() -> None:
    """`regEspTrib=9` só existe a partir da 1.01.

    O `tiposSimples_v1.00.xsd` enumera de 0 a 6; a 1.01 acrescenta o 9. Emitir 9 sob
    o perfil 1.00 produziria um documento que o próprio schema do governo recusa, e
    a `nfelib` só distribui bindings da 1.00 — o erro nativo seria um `ValueError` de
    enum sem contexto nenhum.
    """
    documento = DPS(
        prestador=Prestador(
            cnpj=CNPJ,
            simples_nacional=OpcaoSimplesNacional.MEI,
            regime_especial=RegimeEspecial.OUTROS,
        ),
        servico=Servico(
            codigo="010101", descricao="X", valor=Decimal("1"), municipio_prestacao=MUNICIPIO
        ),
        serie="1",
        numero="1",
        competencia=date(2026, 8, 17),
        municipio_emissor=MUNICIPIO,
        emitido_em=datetime(2026, 8, 17, 10, 0, tzinfo=FUSO_BR),
    )

    with pytest.raises(DadosInvalidosError, match="1.01"):
        serializar(documento, PERFIL_100)


# ------------------------------------------------------- integração até o byte enviado


@pytest.mark.parametrize("perfil", [PERFIL_100, PERFIL_101])
def test_fachada_ate_o_gzip(perfil: Perfil, pfx_valido: object) -> None:
    """O caminho inteiro, na ordem que o `DESIGN.md` fixa e sem volta pelo `xsdata`.

    fachada -> adapter serializa -> `signing.assinar` -> `transport.gzip_b64`. Se
    algo reserializasse no meio, `verificar` falharia aqui.
    """
    certificado = Certificate.from_bytes(
        pfx_valido.blob,  # type: ignore[attr-defined]
        pfx_valido.senha,  # type: ignore[attr-defined]
    )

    xml = serializar(_dps_mei(), perfil)
    assinado = assinar(xml, certificado, perfil)

    assert verificar(assinado, perfil)
    assert gzip_b64(assinado)


def test_referencia_da_assinatura_aponta_para_o_identificador(pfx_valido: object) -> None:
    """`Reference URI` é `"#" + infDPS/@Id`, e o `Id` vem da fachada.

    Se a montagem do identificador e a da assinatura divergirem, a nota é rejeitada
    por um motivo que não menciona nenhum dos dois.
    """
    certificado = Certificate.from_bytes(
        pfx_valido.blob,  # type: ignore[attr-defined]
        pfx_valido.senha,  # type: ignore[attr-defined]
    )
    assinado = assinar(serializar(_dps_mei()), certificado)

    documento = etree.fromstring(assinado)
    referencia = documento.find(".//{http://www.w3.org/2000/09/xmldsig#}Reference")
    assert referencia is not None
    assert referencia.get("URI") == f"#{ID_ESPERADO}"


def test_documento_assinado_continua_valido_no_xsd(
    pfx_valido: object, schema_100: etree.XMLSchema
) -> None:
    """A assinatura entra como irmã de `infDPS`, e o XSD 1.00 é restritivo com ela."""
    certificado = Certificate.from_bytes(
        pfx_valido.blob,  # type: ignore[attr-defined]
        pfx_valido.senha,  # type: ignore[attr-defined]
    )
    documento = etree.fromstring(assinar(serializar(_dps_mei()), certificado))

    assert schema_100.validate(documento), schema_100.error_log
