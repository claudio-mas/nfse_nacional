"""O serviço prestado e o que se cobra por ele.

Aqui mora a promessa do projeto em uma linha: o caminho real do código de serviço é
`dps.infDPS.serv.cServ.cTribNac`, e o valor não é `"01.01"` — é `"010101"`, seis
dígitos. Quem escreve `Servico(codigo="010101", ...)` nunca precisou saber disso.

`buscar_servico("banho e tosa")` resolve o outro lado: achar o código sem abrir a
lista de 337 subitens.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nfse_sefin.catalogos.servicos import por_codigo
from nfse_sefin.errors import DadosInvalidosError
from nfse_sefin.facade.documentos import so_digitos, validar_codigo_municipio, validar_texto
from nfse_sefin.facade.enums import RetencaoISSQN, TributacaoISSQN
from nfse_sefin.facade.tributos import TotalTributos, para_decimal

__all__ = ["Servico"]

_MAX_DECIMAL_15V2 = Decimal("999999999999999.99")
_MAX_ALIQUOTA = Decimal("9.99")


def _monetario(valor: Decimal | int | str, campo: str) -> Decimal:
    """`TSDec15V2`: até 15 inteiros e exatamente 2 decimais, nunca negativo."""
    numero = para_decimal(valor, campo)
    if numero < 0:
        raise DadosInvalidosError(f"{campo}: valor negativo não existe no leiaute ({numero}).")
    if numero > _MAX_DECIMAL_15V2:
        raise DadosInvalidosError(f"{campo}: excede o máximo do leiaute ({numero}).")
    return numero


@dataclass(frozen=True, slots=True)
class Servico:
    """`serv` mais `valores` — o que foi prestado, onde, e por quanto.

    Os dois grupos moram em ramos diferentes da árvore, mas ninguém preenche um sem o
    outro, e separá-los aqui só criaria a chance de esquecer metade.
    """

    codigo: str
    """`cServ/cTribNac` — 6 dígitos da lista nacional. `buscar_servico` acha o seu."""

    descricao: str
    """`cServ/xDescServ` — descrição livre do que foi feito, até 2000 caracteres."""

    valor: Decimal
    """`vServPrest/vServ` — o valor do serviço.

    Tipado como `Decimal`, que é o que um chamador sob `mypy` deve passar. Em runtime
    `str` e `int` também são aceitos e convertidos, porque o valor quase sempre vem de
    JSON ou de uma coluna de banco e forçar a conversão no chamador só moveria o
    problema. `float` é recusado nos dois regimes: `0.1 + 0.2` não é `0.3`, e um
    centavo errado numa nota fiscal não é detalhe de arredondamento.
    """

    municipio_prestacao: str
    """`locPrest/cLocPrestacao` — código IBGE de onde o serviço foi prestado."""

    tributacao_issqn: TributacaoISSQN = TributacaoISSQN.OPERACAO_TRIBUTAVEL
    retencao_issqn: RetencaoISSQN = RetencaoISSQN.NAO_RETIDO

    aliquota: Decimal | None = None
    """`tribMun/pAliq` — só é usada quando o município de incidência não é conveniado.

    Município conveniado tem a alíquota parametrizada no sistema, e a parametrizada
    vence a informada. Deixar `None` é o caso normal.
    """

    codigo_municipal: str | None = None
    """`cServ/cTribMun` — o código da lista municipal, quando o município exige."""

    codigo_interno: str | None = None
    """`cServ/cIntContrib` — identificador da DPS no sistema de quem integra."""

    informacoes_complementares: str | None = None
    """`serv/infoCompl/xInfComp` — texto livre que sai impresso na DANFSe."""

    total_tributos: TotalTributos | None = None
    """`valores/trib/totTrib`. `None` deixa a `DPS` escolher o padrão do regime.

    Só o MEI tem padrão. Ver `facade.tributos`.
    """

    def __post_init__(self) -> None:
        atribuir = object.__setattr__

        codigo = so_digitos(self.codigo)
        if len(codigo) != 6:
            raise DadosInvalidosError(
                f"codigo: cTribNac tem 6 dígitos, recebi {self.codigo!r}. "
                'O leiaute não usa a forma "01.01" da LC 116 — usa "010101".'
            )
        if por_codigo(codigo) is None:
            raise DadosInvalidosError(
                f"codigo: {codigo} não está na lista nacional de serviços. "
                "Use buscar_servico('...') para achar o subitem correto."
            )
        atribuir(self, "codigo", codigo)

        descricao = " ".join(self.descricao.split())
        if not descricao:
            raise DadosInvalidosError("descricao é obrigatória e veio vazia.")
        if len(descricao) > 2000:
            raise DadosInvalidosError(
                f"descricao: o leiaute aceita 2000 caracteres, recebi {len(descricao)}."
            )
        atribuir(self, "descricao", descricao)

        atribuir(self, "valor", _monetario(self.valor, "valor"))
        atribuir(
            self,
            "municipio_prestacao",
            validar_codigo_municipio(self.municipio_prestacao, campo="municipio_prestacao"),
        )

        if self.aliquota is not None:
            aliquota = para_decimal(self.aliquota, "aliquota")
            # `pAliq` é `TSDec1V2`: `0|[0-9]{1}(\.[0-9]{2})?` — **um** dígito inteiro.
            # O teto do XSD é 9,99%, e não é arbitrário: a LC 116 fixa a alíquota
            # máxima do ISSQN em 5%.
            if not 0 <= aliquota <= _MAX_ALIQUOTA:
                raise DadosInvalidosError(
                    f"aliquota: pAliq aceita de 0 a {_MAX_ALIQUOTA}% "
                    f"(um dígito inteiro), recebi {aliquota}."
                )
            atribuir(self, "aliquota", aliquota)

        if self.codigo_municipal is not None:
            municipal = so_digitos(self.codigo_municipal)
            if len(municipal) != 3:
                raise DadosInvalidosError(
                    f"codigo_municipal: cTribMun é `[0-9]{{3}}`, recebi {self.codigo_municipal!r}."
                )
            atribuir(self, "codigo_municipal", municipal)

        if self.codigo_interno is not None:
            interno = self.codigo_interno.strip()
            if not interno.isascii() or not interno.isalnum() or len(interno) > 20:
                raise DadosInvalidosError(
                    f"codigo_interno: cIntContrib é `[a-zA-Z0-9]{{1,20}}` — só letras e "
                    f"dígitos ASCII, sem hífen nem espaço. Recebi {self.codigo_interno!r}."
                )
            atribuir(self, "codigo_interno", interno)

        atribuir(
            self,
            "informacoes_complementares",
            validar_texto(
                self.informacoes_complementares, "informacoes_complementares", maximo=2000
            ),
        )
