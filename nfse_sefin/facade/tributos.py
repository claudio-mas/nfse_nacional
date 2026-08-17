"""O grupo `totTrib`, que é obrigatório e cujo conteúdo depende do Simples Nacional.

Este é o campo do leiaute que mais custa a quem integra pela primeira vez, e o motivo
é que ele junta três coisas que não parecem relacionadas:

1. `totTrib` é **obrigatório** e é um `xs:choice` — exatamente um dos quatro filhos.
2. Qual dos quatro é permitido depende de `prest/regTrib/opSimpNac`, que fica em
   outro ramo da árvore.
3. As três regras que ligam um ao outro não estão no XSD. Estão no Anexo I, como
   rejeições:

   | `opSimpNac` | `indTotTrib` | `pTotTribSN` |
   |---|---|---|
   | 1 — Não Optante | proibido (E0713) | proibido (E0713) |
   | 2 — MEI | permitido | proibido (E0710) |
   | 3 — ME/EPP | proibido (E0712) | permitido |

Logo: MEI declina de informar (`indTotTrib=0`, Decreto 8.264/2014), ME/EPP informa o
percentual do Simples, e Não Optante **precisa** informar valor ou percentual
aproximado dos tributos — é a Lei da Transparência 12.741/2012 chegando pelo leiaute.

Por isso `TotalTributos` não é um dataclass com quatro campos opcionais: é um tipo com
quatro construtores nomeados, e escolher um errado falha aqui em vez de virar `E0712`
depois da assinatura.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from nfse_sefin.errors import DadosInvalidosError
from nfse_sefin.facade.enums import OpcaoSimplesNacional

__all__ = ["TotalTributos", "total_padrao", "checar_total_tributos", "para_decimal"]

Ramo = Literal["indTotTrib", "pTotTribSN", "vTotTrib", "pTotTrib"]


_MAX_PERCENTUAL_SN = Decimal("99.99")
"""`pTotTribSN` é `TSDec2V2`: dois dígitos inteiros. A maior alíquota do Simples é 33%."""

_MAX_PERCENTUAL_ESFERA = Decimal("100")
"""E0706, E0707 e E0708: cada percentual de `pTotTrib` vai de 0 a 100."""

_MAX_VALOR = Decimal("999999999999999.99")
"""`TSDec15V2`."""


def para_decimal(valor: Decimal | int | str, campo: str) -> Decimal:
    """Aceita `Decimal`, `int` ou `str`; recusa `float`.

    `float` fica de fora de propósito: `0.1 + 0.2` não é `0.3`, e um valor fiscal que
    erra no centavo é rejeição ou autuação. `Decimal("150.00")` ou `"150.00"`.
    """
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, bool) or not isinstance(valor, (int, str)):
        raise DadosInvalidosError(
            f"{campo}: use Decimal, int ou str — recebi {type(valor).__name__}. "
            "float não entra em campo monetário porque não representa centavos exatos."
        )
    try:
        return Decimal(str(valor))
    except ArithmeticError as exc:
        raise DadosInvalidosError(f"{campo}: {valor!r} não é um número.") from exc


def _na_faixa(valor: Decimal | int | str, campo: str, maximo: Decimal) -> Decimal:
    numero = para_decimal(valor, campo)
    if not 0 <= numero <= maximo:
        raise DadosInvalidosError(f"{campo}: o leiaute aceita de 0 a {maximo}, recebi {numero}.")
    return numero


@dataclass(frozen=True, slots=True)
class TotalTributos:
    """Um dos quatro ramos de `valores/trib/totTrib`.

    Construa por um dos quatro métodos de classe. O construtor direto existe só
    porque `dataclass` o cria, e usá-lo à mão não é mais curto nem mais claro.
    """

    ramo: Ramo
    percentual_simples_nacional: Decimal | None = None
    federal: Decimal | None = None
    estadual: Decimal | None = None
    municipal: Decimal | None = None

    @classmethod
    def nao_informar(cls) -> TotalTributos:
        """`indTotTrib=0` — o emitente opta por não estimar tributo nenhum.

        Só o MEI pode. Não Optante recebe E0713 e ME/EPP recebe E0712.
        """
        return cls(ramo="indTotTrib")

    @classmethod
    def pelo_simples_nacional(cls, percentual: Decimal | int | str) -> TotalTributos:
        """`pTotTribSN` — percentual aproximado da alíquota do Simples.

        É o número que o contador informa, não algo que a biblioteca possa calcular:
        depende da faixa de receita bruta dos últimos 12 meses.
        """
        return cls(
            ramo="pTotTribSN",
            percentual_simples_nacional=_na_faixa(
                percentual, "percentual_simples_nacional", _MAX_PERCENTUAL_SN
            ),
        )

    @classmethod
    def por_valor(
        cls,
        federal: Decimal | int | str,
        estadual: Decimal | int | str,
        municipal: Decimal | int | str,
    ) -> TotalTributos:
        """`vTotTrib` — valor aproximado em reais, por esfera."""
        return cls(
            ramo="vTotTrib",
            federal=_na_faixa(federal, "federal", _MAX_VALOR),
            estadual=_na_faixa(estadual, "estadual", _MAX_VALOR),
            municipal=_na_faixa(municipal, "municipal", _MAX_VALOR),
        )

    @classmethod
    def por_percentual(
        cls,
        federal: Decimal | int | str,
        estadual: Decimal | int | str,
        municipal: Decimal | int | str,
    ) -> TotalTributos:
        """`pTotTrib` — percentual aproximado, por esfera."""
        return cls(
            ramo="pTotTrib",
            federal=_na_faixa(federal, "federal", _MAX_PERCENTUAL_ESFERA),
            estadual=_na_faixa(estadual, "estadual", _MAX_PERCENTUAL_ESFERA),
            municipal=_na_faixa(municipal, "municipal", _MAX_PERCENTUAL_ESFERA),
        )


def total_padrao(simples: OpcaoSimplesNacional) -> TotalTributos | None:
    """O que dá para preencher sozinho, e só isso.

    MEI tem uma única saída sensata e ela não precisa de nenhum dado externo. Os
    outros dois regimes exigem um número que mora na contabilidade do cliente, e
    chutar zero ali seria declarar tributo estimado de R$ 0,00 em nome dele.
    """
    return TotalTributos.nao_informar() if simples is OpcaoSimplesNacional.MEI else None


_PROIBIDOS: dict[OpcaoSimplesNacional, dict[str, str]] = {
    OpcaoSimplesNacional.NAO_OPTANTE: {
        "indTotTrib": "E0713",
        "pTotTribSN": "E0713",
    },
    OpcaoSimplesNacional.MEI: {"pTotTribSN": "E0710"},
    OpcaoSimplesNacional.ME_EPP: {"indTotTrib": "E0712"},
}

_COMO_RESOLVER: dict[OpcaoSimplesNacional, str] = {
    OpcaoSimplesNacional.NAO_OPTANTE: (
        "Não Optante informa valor ou percentual aproximado dos tributos: "
        "TotalTributos.por_valor(...) ou TotalTributos.por_percentual(...)."
    ),
    OpcaoSimplesNacional.MEI: (
        "MEI usa TotalTributos.nao_informar() — é o padrão quando o campo fica em branco."
    ),
    OpcaoSimplesNacional.ME_EPP: (
        "ME/EPP informa o percentual do Simples: TotalTributos.pelo_simples_nacional('6.00')."
    ),
}


def checar_total_tributos(total: TotalTributos | None, simples: OpcaoSimplesNacional) -> None:
    """Aplica E0710, E0712 e E0713 antes de a DPS sair da máquina.

    As três dependem só de `opSimpNac` e do ramo escolhido, então são decidíveis
    offline — que é o critério de P7 para validar aqui em vez de deixar para o
    servidor.
    """
    if total is None:
        raise DadosInvalidosError(
            "valores/trib/totTrib é obrigatório e não tem padrão para este regime. "
            + _COMO_RESOLVER[simples]
        )

    codigo = _PROIBIDOS[simples].get(total.ramo)
    if codigo is not None:
        raise DadosInvalidosError(
            f"{codigo}: {total.ramo} não é permitido quando opSimpNac é "
            f"{simples.name} ({simples.value}). " + _COMO_RESOLVER[simples]
        )
