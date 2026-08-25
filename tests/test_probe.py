"""Testes do probe de assinatura (9e).

O que se prova aqui é que a feature de manchete **não emite nota**, e que a leitura da
resposta é por camada e não por código:

- **O estrago deliberado existe e é aplicado antes de assinar.** O XML que sai carrega
  `opSimpNac=1` junto com `indTotTrib` — o par E0713 — e a assinatura ainda confere. Se
  o estrago fosse aplicado depois de assinar, o digest quebraria; se não fosse aplicado,
  o probe emitiria uma nota válida.
- **Classificação por camada.** E1235 é recusa da recepção e responde "perfil 1.00".
  Qualquer código de negócio responde "perfil 1.01" — inclusive o de município não
  aderente, que é o que torna convênio dispensável.
- **Produção é recusada antes da rede.** Sem flag de override, e sem requisição nenhuma.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from lxml import etree
from pytest_httpx import HTTPXMock

from nfse_sefin.ambientes import Ambiente, bases_de
from nfse_sefin.cert import Certificate
from nfse_sefin.client import CAMPO_DPS, NFSeClient
from nfse_sefin.errors import DadosInvalidosError, ProbeEmProducaoError
from nfse_sefin.perfis import PERFIL_100, PERFIL_101
from nfse_sefin.probe import (
    PERFIL_DO_PROBE,
    SERIE_PROBE,
    ResultadoProbe,
    Veredito,
    classificar,
    cnpj_do_certificado,
    com_estrago,
    dps_do_probe,
    recusar_producao,
)
from nfse_sefin.signing import verificar
from nfse_sefin.transport import Transporte, de_gzip_b64

BASES_RESTRITA = bases_de(Ambiente.PRODUCAO_RESTRITA)
BASES_PRODUCAO = bases_de(Ambiente.PRODUCAO)

MUNICIPIO = "3304557"
CNPJ_DO_PFX = "12345678000195"
"""O CN de `conftest.CN_EXEMPLO` é `PETSHOP EXEMPLO LTDA:12345678000195`."""

URL_EMITIR = f"{BASES_RESTRITA.sefin}/nfse"
NS = "http://www.sped.fazenda.gov.br/nfse"


@pytest.fixture
def certificado(pfx_valido: Any) -> Certificate:
    return Certificate.from_bytes(pfx_valido.blob, pfx_valido.senha)


def _cliente(certificado: Certificate, **kwargs: Any) -> NFSeClient:
    transporte = Transporte(
        certificate=certificado,
        client=httpx.Client(),
        espera_base=0.01,
        dormir=lambda _: None,
    )
    return NFSeClient(certificado, transporte=transporte, **kwargs)


def _xml_enviado(httpx_mock: HTTPXMock) -> bytes:
    (requisicao,) = httpx_mock.get_requests()
    import json

    return de_gzip_b64(json.loads(requisicao.read())[CAMPO_DPS])


def _erro(*codigos: str) -> dict[str, Any]:
    return {"erro": [{"codigo": c, "descricao": "…"} for c in codigos]}


# ------------------------------------------------------- recusa de produção


def test_producao_e_recusada() -> None:
    with pytest.raises(ProbeEmProducaoError, match="não roda em produção"):
        recusar_producao(Ambiente.PRODUCAO)


def test_producao_restrita_passa() -> None:
    recusar_producao(Ambiente.PRODUCAO_RESTRITA)


def test_probe_em_producao_nao_manda_requisicao(
    certificado: Certificate, httpx_mock: HTTPXMock
) -> None:
    """A recusa vem antes da rede — é isso que impede a nota real.

    Se a checagem rodasse depois de montar e assinar, um erro de ordem no futuro faria
    a DPS sair da máquina antes de alguém perceber.
    """
    cliente = _cliente(certificado, ambiente=Ambiente.PRODUCAO)

    with pytest.raises(ProbeEmProducaoError):
        cliente.probe_assinatura(MUNICIPIO)

    assert httpx_mock.get_requests() == []


# ------------------------------------------------------------- certificado


def test_cnpj_sai_do_common_name(certificado: Certificate) -> None:
    assert cnpj_do_certificado(certificado) == CNPJ_DO_PFX


def test_certificado_sem_cnpj_no_cn_e_recusado(certificado: Certificate) -> None:
    """e-CPF não emite como prestador, e o probe diz isso em vez de montar CNPJ vazio."""
    import dataclasses

    sem_cnpj = dataclasses.replace(certificado, cn="FULANO DE TAL")

    with pytest.raises(DadosInvalidosError, match="e-CNPJ"):
        cnpj_do_certificado(sem_cnpj)


# ----------------------------------------------------- a DPS e o estrago


def test_dps_do_probe_usa_a_serie_reservada() -> None:
    dps = dps_do_probe(CNPJ_DO_PFX, MUNICIPIO, Ambiente.PRODUCAO_RESTRITA)

    assert dps.serie == SERIE_PROBE
    assert dps.ambiente is Ambiente.PRODUCAO_RESTRITA


def test_dps_do_probe_nasce_valida() -> None:
    """A fachada aceita a DPS do probe — o único defeito dela é o que `com_estrago` põe.

    Importa porque uma DPS que já fosse inválida seria recusada por outro motivo, e a
    recusa deixaria de responder a pergunta sobre a assinatura.
    """
    dps = dps_do_probe(CNPJ_DO_PFX, MUNICIPIO, Ambiente.PRODUCAO_RESTRITA)

    assert dps.total_tributos is not None
    assert dps.total_tributos.ramo == "indTotTrib"


def test_com_estrago_produz_o_par_proibido() -> None:
    """`opSimpNac=1` com `indTotTrib` é E0713, e é o que garante a recusa."""
    from nfse_sefin.adapters.nfelib import serializar

    dps = dps_do_probe(CNPJ_DO_PFX, MUNICIPIO, Ambiente.PRODUCAO_RESTRITA)
    limpo = serializar(dps, PERFIL_DO_PROBE)

    assert etree.fromstring(limpo).findtext(f".//{{{NS}}}opSimpNac") == "2"

    estragado = etree.fromstring(com_estrago(limpo))
    assert estragado.findtext(f".//{{{NS}}}opSimpNac") == "1"
    assert estragado.find(f".//{{{NS}}}indTotTrib") is not None


def test_com_estrago_recusa_xml_sem_op_simp_nac() -> None:
    """Sem o estrago o probe emitiria nota válida. Falhar alto é a única saída certa."""
    with pytest.raises(DadosInvalidosError, match="estrago"):
        com_estrago(b'<?xml version="1.0"?><Dps xmlns="http://x"><infDPS/></Dps>')


# ------------------------------------------------------------ classificação


@pytest.mark.parametrize("codigo", ["E1235", "E0714", "E0717", "E0718"])
def test_recusa_de_assinatura_aponta_o_perfil_100(codigo: str) -> None:
    resultado = classificar((codigo,))

    assert resultado.veredito is Veredito.PERFIL_ENCONTRADO
    assert resultado.perfil is PERFIL_100


@pytest.mark.parametrize("codigo", ["E0713", "E1301", "E0014", "E1260", "E1297"])
def test_codigo_de_negocio_aponta_o_perfil_101(codigo: str) -> None:
    """Chegar à regra de negócio significa que a assinatura passou pela recepção.

    `E1260` e `E1297` entram porque são o caso que separa esta implementação da
    atalhada: a recepção ocupa `E1200`-`E1242`, mas a faixa `E12##` **continua** depois
    dela com regra de negócio. Classificar por prefixo numérico em vez de pela seção do
    anexo leria os dois como recusa de recepção e devolveria INDETERMINADO — a resposta
    certa jogada fora por causa do formato do código.

    Esta lista já esteve sem eles, e o teste de mutação foi quem mostrou: trocar a
    consulta ao catálogo por `codigo.startswith("E12")` não quebrava nada.
    """
    resultado = classificar((codigo,))

    assert resultado.veredito is Veredito.PERFIL_ENCONTRADO
    assert resultado.perfil is PERFIL_101


@pytest.mark.parametrize("codigo", ["E1225", "E1228", "E1229", "E1200"])
def test_outra_falha_de_recepcao_e_indeterminada(codigo: str) -> None:
    """Base64, prefixo de namespace ou UTF-8 quebrados são bug nosso, não resposta.

    Lê-los como "então é o outro perfil" trocaria um defeito da biblioteca por um fato
    falso gravado na configuração de quem integra.
    """
    resultado = classificar((codigo,))

    assert resultado.veredito is Veredito.INDETERMINADO
    assert resultado.perfil is None


def test_sem_codigo_nenhum_e_indeterminado() -> None:
    assert classificar(()).veredito is Veredito.INDETERMINADO


def test_recusa_de_assinatura_vence_codigo_de_negocio_junto() -> None:
    """Resposta com os dois: a recusa de assinatura é a que responde a pergunta."""
    resultado = classificar(("E0713", "E1235"))

    assert resultado.perfil is PERFIL_100


# ------------------------------------------------------ o probe ponta a ponta


def test_probe_le_e1235_como_perfil_100(certificado: Certificate, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL_EMITIR, method="POST", status_code=400, json=_erro("E1235"))
    cliente = _cliente(certificado)

    resultado = cliente.probe_assinatura(MUNICIPIO)

    assert resultado.perfil is PERFIL_100
    assert resultado.codigos == ("E1235",)
    assert len(httpx_mock.get_requests()) == 1


def test_probe_le_e0713_como_perfil_101(certificado: Certificate, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL_EMITIR, method="POST", status_code=400, json=_erro("E0713"))
    cliente = _cliente(certificado)

    resultado = cliente.probe_assinatura(MUNICIPIO)

    assert resultado.perfil is PERFIL_101


def test_probe_responde_mesmo_sem_municipio_conveniado(
    certificado: Certificate, httpx_mock: HTTPXMock
) -> None:
    """A metade da OQ12 que caiu: convênio deixou de ser pré-requisito.

    Município não aderente devolve código de negócio, e negócio já significa que a
    assinatura passou pela recepção — que é a única coisa que o probe pergunta.
    """
    httpx_mock.add_response(url=URL_EMITIR, method="POST", status_code=400, json=_erro("E1309"))
    cliente = _cliente(certificado)

    assert cliente.probe_assinatura(MUNICIPIO).perfil is PERFIL_101


def test_probe_envia_o_par_sha256_estragado_e_assinado(
    certificado: Certificate, httpx_mock: HTTPXMock
) -> None:
    """A guarda central: o que sai é E0713, é SHA-256, e a assinatura confere.

    A assinatura conferir prova que o estrago entrou **antes** de assinar. Aplicá-lo
    depois quebraria o digest, e o servidor recusaria por assinatura — que o probe leria
    como "perfil recusado". O resultado seria sempre 1.00, sempre errado.
    """
    httpx_mock.add_response(url=URL_EMITIR, method="POST", status_code=400, json=_erro("E0713"))
    cliente = _cliente(certificado)

    cliente.probe_assinatura(MUNICIPIO)

    xml = _xml_enviado(httpx_mock)
    raiz = etree.fromstring(xml)

    assert raiz.findtext(f".//{{{NS}}}opSimpNac") == "1"
    assert raiz.find(f".//{{{NS}}}indTotTrib") is not None
    assert raiz.findtext(f".//{{{NS}}}serie") == SERIE_PROBE
    assert PERFIL_101.algoritmo_assinatura.encode() in xml
    assert verificar(xml, PERFIL_101)


def test_probe_ignora_o_perfil_do_cliente(certificado: Certificate, httpx_mock: HTTPXMock) -> None:
    """Mandar SHA-1 passaria nos dois schemas e não responderia nada."""
    httpx_mock.add_response(url=URL_EMITIR, method="POST", status_code=400, json=_erro("E0713"))
    cliente = _cliente(certificado, perfil=PERFIL_100)

    cliente.probe_assinatura(MUNICIPIO)

    assert PERFIL_101.algoritmo_assinatura.encode() in _xml_enviado(httpx_mock)


def test_probe_aceito_e_defeito_e_devolve_a_chave(
    certificado: Certificate, httpx_mock: HTTPXMock
) -> None:
    """Contingência: o estrago não segurou e existe uma nota para cancelar à mão."""
    chave = "1" * 50
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json={"chaveAcesso": chave})
    cliente = _cliente(certificado)

    resultado = cliente.probe_assinatura(MUNICIPIO)

    assert resultado.veredito is Veredito.NOTA_GERADA
    assert resultado.perfil is None
    assert resultado.chave_acesso == chave
    assert "cancelada à mão" in resultado.motivo


def test_resultado_se_descreve_pelo_motivo() -> None:
    resultado = ResultadoProbe(
        veredito=Veredito.INDETERMINADO, perfil=None, codigos=(), motivo="qualquer coisa"
    )

    assert str(resultado) == "qualquer coisa"
