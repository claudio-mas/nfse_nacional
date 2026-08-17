"""A DPS — Declaração de Prestação de Serviços.

É o documento que o contribuinte envia; a NFS-e é o que a SEFIN devolve. Quem integra
monta uma `DPS`, o cliente emite, e a nota volta.

## O identificador de 45 posições

`infDPS/@Id` não é um UUID nem um número que o servidor atribui: é a concatenação de
campos que já estão no documento, e informar qualquer coisa diferente disso é `E0004`.

    "DPS" + cLocEmi(7) + tipoInscrição(1) + inscriçãoFederal(14) + série(5) + nDPS(15)

Note o zero à esquerda: no elemento `<serie>` vai `900`, no identificador vai `00900`.
O mesmo para `nDPS`. Errar essa diferença é rejeição, e é o tipo de detalhe que esta
classe existe para absorver.

## A armadilha do `dhEmi`

`TSDateTimeUTC` exige `AAAA-MM-DDThh:mm:ss±hh:00` — offset obrigatório, minutos
sempre `00`, e **sem microssegundos**. `datetime.now(tz).isoformat()` devolve
`2026-08-17T10:00:00.123456-03:00`, que o schema recusa. `DPS` remove o
microssegundo sozinha, porque descobrir isso pela rejeição custa caro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from nfse_sefin._version import __version__
from nfse_sefin.ambientes import Ambiente
from nfse_sefin.errors import DadosInvalidosError
from nfse_sefin.facade.documentos import so_digitos, validar_codigo_municipio
from nfse_sefin.facade.enums import TipoEmitente
from nfse_sefin.facade.pessoa import Prestador, Tomador
from nfse_sefin.facade.servico import Servico
from nfse_sefin.facade.tributos import TotalTributos, checar_total_tributos, total_padrao

__all__ = ["DPS", "VERSAO_APLICACAO"]

VERSAO_APLICACAO = f"nfse-sefin {__version__}"
"""`infDPS/verAplic` — `TSVerAplic` aceita de 1 a 20 caracteres."""


def _agora() -> datetime:
    """Momento presente com fuso, sem microssegundo. Ver a nota do módulo."""
    return datetime.now().astimezone().replace(microsecond=0)


@dataclass(frozen=True, slots=True)
class DPS:
    """Uma declaração pronta para assinar e enviar.

    A biblioteca **não** é dona da sequência: `serie` e `numero` vêm de quem integra,
    e garantir que o par não se repita é responsabilidade do ERP hospedeiro. É
    deliberado — `E0014` rejeita série+número+município+CNPJ repetidos, e um contador
    interno de biblioteca seria uma promessa de unicidade que ela não pode cumprir
    entre processos, máquinas ou reinícios.
    """

    prestador: Prestador
    servico: Servico

    serie: str
    """`infDPS/serie`, 1 a 5 dígitos. Emissão por aplicativo próprio usa 1 a 49999."""

    numero: str
    """`infDPS/nDPS`, o sequencial do emitente. Sem zero à esquerda, começa em 1."""

    competencia: date
    """`infDPS/dCompet` — data completa AAAA-MM-DD, não a competência AAAA-MM."""

    municipio_emissor: str
    """`infDPS/cLocEmi` — código IBGE do município onde o emitente está cadastrado."""

    tomador: Tomador | None = None
    emitido_em: datetime = field(default_factory=_agora)
    ambiente: Ambiente = Ambiente.PRODUCAO_RESTRITA
    """Padrão conservador. `NFSeClient.emitir` sobrescreve com o ambiente do cliente."""

    tipo_emitente: TipoEmitente = TipoEmitente.PRESTADOR
    versao_aplicacao: str = VERSAO_APLICACAO

    def __post_init__(self) -> None:
        atribuir = object.__setattr__

        serie = so_digitos(self.serie)
        if not serie or len(serie) > 5 or int(serie) == 0:
            raise DadosInvalidosError(
                f"serie: 1 a 5 dígitos, maior que zero. Recebi {self.serie!r}."
            )
        atribuir(self, "serie", str(int(serie)))

        numero = so_digitos(self.numero)
        if not numero or len(numero) > 15 or int(numero) == 0:
            raise DadosInvalidosError(
                f"numero: 1 a 15 dígitos, maior que zero. Recebi {self.numero!r}."
            )
        atribuir(self, "numero", str(int(numero)))

        atribuir(
            self,
            "municipio_emissor",
            validar_codigo_municipio(self.municipio_emissor, campo="municipio_emissor"),
        )

        if self.emitido_em.tzinfo is None or self.emitido_em.utcoffset() is None:
            raise DadosInvalidosError(
                "emitido_em: o leiaute exige fuso horário explícito e não tem padrão "
                "para datetime ingênuo. Use datetime.now().astimezone()."
            )
        deslocamento = self.emitido_em.utcoffset()
        assert deslocamento is not None  # garantido pela checagem acima
        if deslocamento.total_seconds() % 3600:
            raise DadosInvalidosError(
                f"emitido_em: TSDateTimeUTC só aceita fuso em horas inteiras, "
                f"recebi {deslocamento}."
            )
        atribuir(self, "emitido_em", self.emitido_em.replace(microsecond=0))

        if len(self.versao_aplicacao) > 20:
            raise DadosInvalidosError(
                f"versao_aplicacao: verAplic aceita 20 caracteres, "
                f"recebi {len(self.versao_aplicacao)}."
            )

        checar_total_tributos(self.total_tributos, self.prestador.simples_nacional)

    @property
    def total_tributos(self) -> TotalTributos | None:
        """O ramo de `totTrib` a emitir: o que o chamador escolheu, ou o do regime."""
        if self.servico.total_tributos is not None:
            return self.servico.total_tributos
        return total_padrao(self.prestador.simples_nacional)

    @property
    def identificador(self) -> str:
        """`infDPS/@Id` — as 45 posições, montadas na ordem que `E0004` exige."""
        return (
            "DPS"
            + self.municipio_emissor
            + self.prestador.tipo_inscricao
            + self.prestador.inscricao_federal
            + self.serie.zfill(5)
            + self.numero.zfill(15)
        )
