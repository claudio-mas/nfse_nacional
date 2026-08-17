"""O único módulo que importa `nfelib`, e o único que serializa.

Tudo que sabe o que é `TcinfDps`, `Tccserv` ou `XmlSerializer` está aqui. A fachada
não sabe, os testes dela não precisam da dependência, e quando um ZIP novo do governo
mudar o leiaute é este arquivo que quebra — não seis.

## Três coisas que este módulo garante e não podem ser afrouxadas

**`ns_map={None: NAMESPACE}`.** Sem ele o `xsdata` emite `ns0:DPS`, e a recepção
rejeita com E1228 (`RN_RECEPCAO_DPS` #14) antes de olhar o conteúdo. É a diferença
entre um teste que passa e uma integração que nunca funcionou.

**UTF-8 com declaração.** E1229 (`RN_RECEPCAO_DPS` #15).

**Serialização única.** `serializar` devolve bytes, e esses bytes vão para
`signing.assinar` e de lá direto para `transport.gzip_b64`. Nada volta pelo `xsdata`
no meio: uma segunda passada reescreve declarações de namespace e o digest da
assinatura deixa de bater com a árvore — sem erro, sem aviso, só rejeição.

## Um único conjunto de bindings para os dois perfis

A `nfelib` 2.5.2 só distribui bindings da 1.00. O perfil 1.01 usa os mesmos bindings
com `versao="1.01"`, o que é exatamente o que o Approach C precisa: mesma árvore,
atributo e par de hash diferentes. Funciona porque todo campo que emitimos tem forma
idêntica nas duas versões — o que a 1.01 acrescenta (IBS/CBS) está fora do escopo de
v0.2.0. A exceção conhecida é `regEspTrib=9`, e ela é recusada explicitamente abaixo.
"""

from __future__ import annotations

from decimal import Decimal

from nfelib.nfse.bindings.v1_0.dps_v1_00 import Dps
from nfelib.nfse.bindings.v1_0.tipos_complexos_v1_00 import (
    Tccserv,
    Tcendereco,
    TcenderNac,
    TcinfDps,
    TcinfoCompl,
    TcinfoPessoa,
    TcinfoPrestador,
    TcinfoTributacao,
    TcinfoValores,
    TclocPrest,
    TcregTrib,
    Tcserv,
    TctribMunicipal,
    TctribTotal,
    TctribTotalMonet,
    TctribTotalPercent,
    TcvservPrest,
)
from nfelib.nfse.bindings.v1_0.tipos_simples_v1_00 import (
    TsemitenteDps,
    TsopSimpNac,
    TsregEspTrib,
    TsregimeApuracaoSimpNac,
    TstipoAmbiente,
    TstipoIndTotTrib,
    TstipoRetIssqn,
    TstribIssqn,
)
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from nfse_sefin.errors import DadosInvalidosError
from nfse_sefin.facade.dps import DPS
from nfse_sefin.facade.enums import RegimeEspecial
from nfse_sefin.facade.pessoa import Endereco, Prestador, Tomador
from nfse_sefin.facade.tributos import TotalTributos
from nfse_sefin.perfis import PERFIL_PADRAO, Perfil

__all__ = ["NAMESPACE", "construir", "serializar"]

NAMESPACE = "http://www.sped.fazenda.gov.br/nfse"


def _dec(valor: Decimal | None) -> str | None:
    """Formata para `TSDec15V2`: `0|0\\.\\d{2}|[1-9]\\d{0,14}(\\.\\d{2})?`.

    O padrão do XSD recusa zero à esquerda (`0150.00`) e recusa uma casa decimal só
    (`150.5`). `:.2f` acerta os dois casos, inclusive `0` → `0.00`.
    """
    return None if valor is None else f"{valor:.2f}"


def _endereco(endereco: Endereco | None) -> Tcendereco | None:
    if endereco is None:
        return None
    return Tcendereco(
        endNac=TcenderNac(cMun=endereco.municipio, CEP=endereco.cep),
        xLgr=endereco.logradouro,
        nro=endereco.numero,
        xCpl=endereco.complemento,
        xBairro=endereco.bairro,
    )


def _prestador(prestador: Prestador, perfil: Perfil) -> TcinfoPrestador:
    if prestador.regime_especial is RegimeEspecial.OUTROS and perfil.versao == "1.00":
        raise DadosInvalidosError(
            "regime_especial=OUTROS (regEspTrib=9) só existe a partir do leiaute 1.01; "
            f"o perfil ativo é {perfil.nome}. O tiposSimples_v1.00.xsd enumera de 0 a 6. "
            "Use o perfil 1.01+SHA256 ou escolha outro regime especial."
        )

    return TcinfoPrestador(
        CNPJ=prestador.cnpj,
        CPF=prestador.cpf,
        IM=prestador.inscricao_municipal,
        xNome=prestador.nome,
        end=_endereco(prestador.endereco),
        fone=prestador.telefone,
        email=prestador.email,
        regTrib=TcregTrib(
            opSimpNac=TsopSimpNac(prestador.simples_nacional.value),
            regApTribSN=(
                None
                if prestador.regime_apuracao_sn is None
                else TsregimeApuracaoSimpNac(prestador.regime_apuracao_sn.value)
            ),
            regEspTrib=TsregEspTrib(prestador.regime_especial.value),
        ),
    )


def _tomador(tomador: Tomador | None) -> TcinfoPessoa | None:
    if tomador is None:
        return None
    return TcinfoPessoa(
        CNPJ=tomador.cnpj,
        CPF=tomador.cpf,
        IM=tomador.inscricao_municipal,
        xNome=tomador.nome,
        end=_endereco(tomador.endereco),
        fone=tomador.telefone,
        email=tomador.email,
    )


def _total_tributos(total: TotalTributos) -> TctribTotal:
    """Emite o único filho permitido do `xs:choice`.

    Qual deles é permitido já foi decidido em `facade.tributos`; aqui só se traduz.
    """
    if total.ramo == "indTotTrib":
        return TctribTotal(indTotTrib=TstipoIndTotTrib.VALUE_0)
    if total.ramo == "pTotTribSN":
        return TctribTotal(pTotTribSN=_dec(total.percentual_simples_nacional))
    if total.ramo == "vTotTrib":
        return TctribTotal(
            vTotTrib=TctribTotalMonet(
                vTotTribFed=_dec(total.federal),
                vTotTribEst=_dec(total.estadual),
                vTotTribMun=_dec(total.municipal),
            )
        )
    return TctribTotal(
        pTotTrib=TctribTotalPercent(
            pTotTribFed=_dec(total.federal),
            pTotTribEst=_dec(total.estadual),
            pTotTribMun=_dec(total.municipal),
        )
    )


def construir(dps: DPS, perfil: Perfil = PERFIL_PADRAO) -> Dps:
    """Traduz a fachada para o binding gerado. Não serializa nem assina."""
    servico = dps.servico

    total = dps.total_tributos
    if total is None:  # pragma: no cover — DPS.__post_init__ já teria recusado
        raise DadosInvalidosError("valores/trib/totTrib ficou sem ramo definido.")

    inf = TcinfDps(
        tpAmb=TstipoAmbiente(dps.ambiente.tp_amb),
        dhEmi=dps.emitido_em.isoformat(),
        verAplic=dps.versao_aplicacao,
        serie=dps.serie,
        nDPS=dps.numero,
        dCompet=dps.competencia.isoformat(),
        tpEmit=TsemitenteDps(dps.tipo_emitente.value),
        cLocEmi=dps.municipio_emissor,
        prest=_prestador(dps.prestador, perfil),
        toma=_tomador(dps.tomador),
        serv=Tcserv(
            locPrest=TclocPrest(cLocPrestacao=servico.municipio_prestacao),
            cServ=Tccserv(
                cTribNac=servico.codigo,
                cTribMun=servico.codigo_municipal,
                xDescServ=servico.descricao,
                cIntContrib=servico.codigo_interno,
            ),
            infoCompl=(
                None
                if servico.informacoes_complementares is None
                else TcinfoCompl(xInfComp=servico.informacoes_complementares)
            ),
        ),
        valores=TcinfoValores(
            vServPrest=TcvservPrest(vServ=_dec(servico.valor)),
            trib=TcinfoTributacao(
                tribMun=TctribMunicipal(
                    tribISSQN=TstribIssqn(servico.tributacao_issqn.value),
                    pAliq=_dec(servico.aliquota),
                    tpRetISSQN=TstipoRetIssqn(servico.retencao_issqn.value),
                ),
                totTrib=_total_tributos(total),
            ),
        ),
        Id=dps.identificador,
    )
    return Dps(infDPS=inf, versao=perfil.versao)


def serializar(dps: DPS, perfil: Perfil = PERFIL_PADRAO) -> bytes:
    """Os bytes que vão para `signing.assinar`, e de lá para o gzip.

    Chame **uma vez**. Reserializar depois de assinar quebra o digest em silêncio.
    """
    config = SerializerConfig(indent=None, xml_declaration=True, encoding="UTF-8")
    texto = XmlSerializer(config=config).render(construir(dps, perfil), ns_map={None: NAMESPACE})
    return texto.encode("utf-8")
