"""Os códigos do leiaute, com nome.

O leiaute fala em `"3"`. O Anexo I diz que `"3"` é "Optante - Microempresa ou Empresa
de Pequeno Porte (ME/EPP)". Entre um e outro há uma tabela de 373 KB exportada de
Excel, e é isso que este módulo remove do caminho.

Cada valor é exatamente o que vai no XML. Cada nome é o que o Anexo I escreve. A
tradução é literal de propósito: inventar um nome mais bonito que o do documento
oficial faria o dev não achar a regra quando a SEFIN rejeitasse.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "TipoEmitente",
    "OpcaoSimplesNacional",
    "RegimeApuracaoSN",
    "RegimeEspecial",
    "TributacaoISSQN",
    "RetencaoISSQN",
]


class TipoEmitente(str, Enum):
    """`infDPS/tpEmit` — quem está emitindo a DPS.

    `TOMADOR` e `INTERMEDIARIO` são recusados pelo sistema nesta versão da aplicação
    (E9996), mas estão aqui porque o leiaute os define e a rejeição é do servidor,
    não nossa.
    """

    PRESTADOR = "1"
    TOMADOR = "2"
    INTERMEDIARIO = "3"


class OpcaoSimplesNacional(str, Enum):
    """`prest/regTrib/opSimpNac` — situação perante o Simples Nacional.

    Decide qual ramo do grupo `totTrib` é permitido. Ver `facade.tributos`.
    """

    NAO_OPTANTE = "1"
    MEI = "2"
    ME_EPP = "3"


class RegimeApuracaoSN(str, Enum):
    """`prest/regTrib/regApTribSN` — só faz sentido para `ME_EPP`.

    É a opção de quem ultrapassou sublimite do Simples e passa a apurar parte dos
    tributos fora dele.
    """

    FEDERAIS_E_MUNICIPAL_PELO_SN = "1"
    FEDERAIS_PELO_SN_ISSQN_PELO_MUNICIPIO = "2"
    FEDERAIS_E_MUNICIPAL_FORA_DO_SN = "3"


class RegimeEspecial(str, Enum):
    """`prest/regTrib/regEspTrib` — regime especial de tributação municipal.

    `OUTROS` existe **só a partir da 1.01**. O `tiposSimples_v1.00.xsd` enumera de
    `0` a `6`; a 1.01 acrescenta `9`. O adapter recusa `OUTROS` sob o perfil 1.00 em
    vez de emitir um valor que o schema não conhece.
    """

    NENHUM = "0"
    ATO_COOPERADO = "1"
    ESTIMATIVA = "2"
    MICROEMPRESA_MUNICIPAL = "3"
    NOTARIO_OU_REGISTRADOR = "4"
    PROFISSIONAL_AUTONOMO = "5"
    SOCIEDADE_DE_PROFISSIONAIS = "6"
    OUTROS = "9"


class TributacaoISSQN(str, Enum):
    """`valores/trib/tribMun/tribISSQN` — como o ISSQN incide sobre o serviço."""

    OPERACAO_TRIBUTAVEL = "1"
    IMUNIDADE = "2"
    EXPORTACAO = "3"
    NAO_INCIDENCIA = "4"


class RetencaoISSQN(str, Enum):
    """`valores/trib/tribMun/tpRetISSQN` — quem recolhe o ISSQN."""

    NAO_RETIDO = "1"
    RETIDO_PELO_TOMADOR = "2"
    RETIDO_PELO_INTERMEDIARIO = "3"
