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

from enum import Enum
from typing import Any, cast

import httpx
import pytest
from lxml import etree
from pytest_httpx import HTTPXMock

from nfse_sefin.ambientes import Ambiente, bases_de
from nfse_sefin.cert import Certificate
from nfse_sefin.client import CAMPO_DPS, NFSeClient
from nfse_sefin.errors import DadosInvalidosError, ProbeEmProducaoError, TransporteError
from nfse_sefin.perfis import PERFIL_100, PERFIL_101
from nfse_sefin.probe import (
    FUSO_DO_PROBE,
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
    with pytest.raises(ProbeEmProducaoError, match="só roda em"):
        recusar_producao(Ambiente.PRODUCAO)


def test_producao_restrita_passa() -> None:
    recusar_producao(Ambiente.PRODUCAO_RESTRITA)


def test_so_producao_restrita_passa_em_toda_a_enum() -> None:
    """Varre a enum inteira: exatamente um membro passa."""
    liberados = []
    for ambiente in Ambiente:
        try:
            recusar_producao(ambiente)
        except ProbeEmProducaoError:
            continue
        liberados.append(ambiente)

    assert liberados == [Ambiente.PRODUCAO_RESTRITA]


def test_ambiente_novo_e_recusado_por_padrao() -> None:
    """A guarda é lista de **permissão**, e é isto que prova a diferença.

    `Ambiente` tem dois membros hoje, então varrer a enum não separa `is not
    PRODUCAO_RESTRITA` de `is PRODUCAO` — as duas formas concordam em tudo que existe.
    Foi o teste de mutação que mostrou: trocar uma pela outra deixava a suíte verde.

    O que separa é um ambiente que ainda não existe. `Ambiente` é API pública e
    `ambientes.py` já carrega quatro URLs base por ambiente; um terceiro membro é adição
    plausível, e sob a negação ele passaria em silêncio — numa guarda cujo modo de falha
    é emitir documento fiscal real.

    O substituto é uma enum de verdade, e não um `object()`, porque a mensagem de erro
    lê `.value`: um dublê sem esse atributo faria a guarda levantar `AttributeError` e o
    teste passaria pelo motivo errado.
    """

    class AmbienteFuturo(str, Enum):
        HOMOLOGACAO = "homologacao"

    futuro = cast(Ambiente, AmbienteFuturo.HOMOLOGACAO)

    with pytest.raises(ProbeEmProducaoError, match="homologacao"):
        recusar_producao(futuro)


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


def test_cnpj_sai_do_othername_quando_o_cn_nao_tem(pfx_cnpj_no_othername: Any) -> None:
    """O certificado que a versão anterior recusava, e que é a forma normativa.

    Ler só o `CN` é convenção. O lugar que E1209 cobra é o `otherName` do SAN, e um
    certificado que siga o padrão sem repetir o CNPJ no CN é perfeitamente válido.
    """
    cert = Certificate.from_bytes(pfx_cnpj_no_othername.blob, pfx_cnpj_no_othername.senha)

    assert cnpj_do_certificado(cert) == "12345678000195"


def test_e_cpf_tem_mensagem_propria(pfx_e_cpf: Any) -> None:
    """ "Isto é e-CPF" e "não achei CNPJ" são problemas diferentes para quem vai emitir."""
    cert = Certificate.from_bytes(pfx_e_cpf.blob, pfx_e_cpf.senha)

    with pytest.raises(DadosInvalidosError, match="e-CPF"):
        cnpj_do_certificado(cert)


def test_certificado_sem_identificacao_nenhuma(pfx_sem_identificacao: Any) -> None:
    cert = Certificate.from_bytes(pfx_sem_identificacao.blob, pfx_sem_identificacao.senha)

    with pytest.raises(DadosInvalidosError, match="Não achei CNPJ"):
        cnpj_do_certificado(cert)


# ----------------------------------------------------- a DPS e o estrago


def test_dps_do_probe_usa_a_serie_reservada() -> None:
    dps = dps_do_probe(CNPJ_DO_PFX, MUNICIPIO, Ambiente.PRODUCAO_RESTRITA)

    assert dps.serie == SERIE_PROBE
    assert dps.ambiente is Ambiente.PRODUCAO_RESTRITA


def test_dps_do_probe_nao_depende_do_fuso_da_maquina() -> None:
    """`TSDateTimeUTC` só aceita fuso em horas inteiras.

    Num host em Asia/Kolkata (+05:30) ou Australia/Adelaide (+09:30),
    `datetime.now().astimezone()` produz meia hora e a fachada recusa a DPS — o probe
    morreria por causa do relógio da máquina, num diagnóstico que não tem nada a ver com
    isso. O documento é descartado de qualquer jeito, então o fuso é fixo.
    """
    dps = dps_do_probe(CNPJ_DO_PFX, MUNICIPIO, Ambiente.PRODUCAO_RESTRITA)

    deslocamento = dps.emitido_em.utcoffset()
    assert deslocamento is not None
    assert deslocamento.total_seconds() % 3600 == 0
    assert dps.emitido_em.tzinfo is FUSO_DO_PROBE


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


@pytest.mark.parametrize("codigo", ["E1235", "E0714"])
def test_recusa_de_assinatura_aponta_o_perfil_100(codigo: str) -> None:
    resultado = classificar((codigo,))

    assert resultado.veredito is Veredito.PERFIL_ENCONTRADO
    assert resultado.perfil is PERFIL_100


@pytest.mark.parametrize("codigo", ["E0715", "E0716", "E0717", "E0718"])
def test_defeito_no_nosso_certificado_nao_vira_recomendacao(codigo: str) -> None:
    """Recusa que fala do nosso certificado ou da nossa assinatura não responde nada.

    E0717 ("a assinatura é obrigatória") é o servidor não achando `Signature` nenhuma —
    defeito de envelope, da mesma classe de E1228. E0718 ("deve ser feita com o
    certificado do emitente") é o CNPJ que assinou não bater com o que emite. Antes de
    2026-08-25 os dois estavam em `CODIGOS_QUE_RECUSAM_O_PERFIL` e viravam um confiante
    "use 1.00+SHA1" — transformando bug nosso em configuração permanente do usuário.
    """
    resultado = classificar((codigo,))

    assert resultado.veredito is Veredito.INDETERMINADO
    assert resultado.perfil is None
    assert "certificado" in resultado.motivo


def test_versao_recusada_e_meia_resposta_e_diz_isso() -> None:
    """E0001 separa os dois eixos que `Perfil` amarra, e o probe não escolhe por conta.

    `Perfil` carrega versão de leiaute **e** par de hash. E0001 ("o prazo de aceitação da
    versão do leiaute da DPS expirou") chega pela camada de negócio, então pela regra
    geral significaria "a assinatura passou, use 1.01" — recomendando justamente a versão
    que o servidor acabou de recusar.
    """
    resultado = classificar(("E0001",))

    assert resultado.veredito is Veredito.INDETERMINADO
    assert resultado.perfil is None
    assert "1.01" in resultado.motivo
    assert "SHA-256" in resultado.motivo or "sha256" in resultado.motivo


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


@pytest.mark.parametrize("codigo", ["401", "503", "ERRO", "E123", "E12345"])
def test_codigo_fora_da_forma_do_anexo_nao_responde_perfil(codigo: str) -> None:
    """Um `401` de proxy chega pelo mesmo campo `codigo` que um `E####`.

    Sem o filtro de forma, ele cairia no ramo "chegou à regra de negócio" e o probe
    recomendaria um perfil apoiado num erro de rede. `client.py` mantém a mesma
    disciplina com `_CODIGO_DE_REJEICAO` para separar rejeição de falha HTTP.
    """
    resultado = classificar((codigo,))

    assert resultado.veredito is Veredito.INDETERMINADO
    assert resultado.perfil is None


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


def test_falha_sem_resposta_nao_vira_veredito(
    certificado: Certificate, httpx_mock: HTTPXMock
) -> None:
    """Conexão que morre sem status não é "o servidor recusou sem código".

    A DPS pode ter sido processada. Classificar aqui esconderia a causa real (rede,
    timeout, mTLS) **e** o fato de que pode existir uma nota — e o probe devolveria
    INDETERMINADO como se o servidor tivesse respondido alguma coisa.
    """
    httpx_mock.add_exception(httpx.ReadTimeout("estourou"), url=URL_EMITIR, method="POST")
    cliente = _cliente(certificado)

    with pytest.raises(TransporteError) as capturado:
        cliente.probe_assinatura(MUNICIPIO)

    erro = capturado.value
    assert erro.status_code is None
    assert "NÃO reenvie" in str(erro)
    assert "dps_foi_processada" in str(erro)


def test_nota_gerada_com_chave_irreconhecivel_ainda_reporta(
    certificado: Certificate, httpx_mock: HTTPXMock
) -> None:
    """Normalizar a chave aqui trocaria "a nota é esta" por uma exceção.

    E a exceção seria `DadosInvalidosError`, que o `doctor` reporta como "o probe não
    pôde ser montado" — dizendo que nada foi enviado enquanto um documento fiscal existe
    e ninguém sabe o número dele.
    """
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json={"chaveAcesso": "123-abc"})
    cliente = _cliente(certificado)

    resultado = cliente.probe_assinatura(MUNICIPIO)

    assert resultado.veredito is Veredito.NOTA_GERADA
    assert resultado.chave_acesso == "123-abc"


def test_nota_gerada_sem_chave_devolve_o_id_da_dps(
    certificado: Certificate, httpx_mock: HTTPXMock
) -> None:
    """Sem chave no corpo, o identificador da DPS é o que ainda acha a nota."""
    httpx_mock.add_response(url=URL_EMITIR, method="POST", json={"campoNovo": "…"})
    cliente = _cliente(certificado)

    resultado = cliente.probe_assinatura(MUNICIPIO)

    assert resultado.veredito is Veredito.NOTA_GERADA
    assert resultado.chave_acesso == ""
    assert resultado.id_dps.startswith("DPS")
    assert SERIE_PROBE.zfill(5) in resultado.id_dps


def test_resultado_se_descreve_pelo_motivo() -> None:
    resultado = ResultadoProbe(
        veredito=Veredito.INDETERMINADO, perfil=None, codigos=(), motivo="qualquer coisa"
    )

    assert str(resultado) == "qualquer coisa"
