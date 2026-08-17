"""Prestador, tomador e endereço.

Dados puros. Nenhum import de `nfelib` aqui, nem em nenhum outro módulo de `facade/`
— é o que mantém a fachada testável sem a dependência e concentra a quebra de
mapeamento num arquivo só quando o leiaute mudar.

O que estes tipos **não** cobrem, de propósito, porque nada em v0.2.0 os usa:
tomador estrangeiro (`NIF`, `cNaoNIF`, `endExt`) e `CAEPF`. Entram junto com
exportação de serviço, com o grupo `comExt` que ela exige.
"""

from __future__ import annotations

from dataclasses import dataclass

from nfse_sefin.errors import DadosInvalidosError
from nfse_sefin.facade.documentos import (
    validar_cep,
    validar_cnpj,
    validar_codigo_municipio,
    validar_cpf,
    validar_telefone,
    validar_texto,
    validar_texto_obrigatorio,
)
from nfse_sefin.facade.enums import OpcaoSimplesNacional, RegimeApuracaoSN, RegimeEspecial

__all__ = ["Endereco", "Prestador", "Tomador"]


@dataclass(frozen=True, slots=True)
class Endereco:
    """`end` — endereço nacional.

    `municipio` é o código IBGE de 7 dígitos, não o nome. É o mesmo código que vai em
    `cLocEmi` e em `cLocPrestacao`, e trocá-lo pelo nome da cidade é o erro de
    preenchimento mais comum aqui.
    """

    logradouro: str
    numero: str
    bairro: str
    municipio: str
    cep: str
    complemento: str | None = None

    def __post_init__(self) -> None:
        atribuir = object.__setattr__
        atribuir(
            self, "logradouro", validar_texto_obrigatorio(self.logradouro, "logradouro", maximo=255)
        )
        atribuir(self, "numero", validar_texto_obrigatorio(self.numero, "numero", maximo=60))
        atribuir(self, "bairro", validar_texto_obrigatorio(self.bairro, "bairro", maximo=60))
        atribuir(self, "municipio", validar_codigo_municipio(self.municipio, campo="municipio"))
        atribuir(self, "cep", validar_cep(self.cep))
        atribuir(self, "complemento", validar_texto(self.complemento, "complemento", maximo=156))


@dataclass(frozen=True, slots=True)
class _Pessoa:
    """Base dos campos de identificação, comuns a prestador e tomador."""

    cnpj: str | None = None
    cpf: str | None = None
    nome: str | None = None
    inscricao_municipal: str | None = None
    endereco: Endereco | None = None
    telefone: str | None = None
    email: str | None = None

    def __post_init__(self) -> None:
        atribuir = object.__setattr__
        if (self.cnpj is None) == (self.cpf is None):
            raise DadosInvalidosError(
                f"{type(self).__name__}: informe exatamente um entre cnpj e cpf. "
                "O leiaute usa um `choice` — os dois juntos, ou nenhum, é rejeição."
            )
        if self.cnpj is not None:
            atribuir(self, "cnpj", validar_cnpj(self.cnpj))
        if self.cpf is not None:
            atribuir(self, "cpf", validar_cpf(self.cpf))

        atribuir(self, "nome", validar_texto(self.nome, "nome", maximo=300))
        atribuir(
            self,
            "inscricao_municipal",
            validar_texto(self.inscricao_municipal, "inscricao_municipal", maximo=15),
        )
        atribuir(self, "telefone", validar_telefone(self.telefone))
        atribuir(self, "email", validar_texto(self.email, "email", maximo=80))

    @property
    def tipo_inscricao(self) -> str:
        """`"1"` para CPF, `"2"` para CNPJ — como entra no identificador da DPS."""
        return "1" if self.cpf is not None else "2"

    @property
    def inscricao_federal(self) -> str:
        """A inscrição em 14 posições, para o identificador.

        O Anexo I manda "CPF completar com 000 à esquerda". É zero à esquerda mesmo,
        não o CPF repetido nem espaço.
        """
        return self.cpf.rjust(14, "0") if self.cpf is not None else str(self.cnpj)


@dataclass(frozen=True, slots=True)
class Prestador(_Pessoa):
    """`prest` — quem presta o serviço.

    `regTrib` é obrigatório no leiaute, e os defaults daqui são os do caso mais
    comum: empresa fora do Simples, sem regime especial municipal.

    `regime_apuracao_sn` só faz sentido para `ME_EPP`; informar em outro regime é
    ruído que o servidor pode recusar, então a fachada o omite quando não se aplica.
    """

    simples_nacional: OpcaoSimplesNacional = OpcaoSimplesNacional.NAO_OPTANTE
    regime_apuracao_sn: RegimeApuracaoSN | None = None
    regime_especial: RegimeEspecial = RegimeEspecial.NENHUM


@dataclass(frozen=True, slots=True)
class Tomador(_Pessoa):
    """`toma` — quem contrata o serviço. Opcional na DPS.

    Diferença de forma para o prestador: aqui `xNome` é obrigatório no leiaute. É a
    única validação extra.
    """

    def __post_init__(self) -> None:
        # `_Pessoa.__post_init__` explícito, não `super()`: `@dataclass(slots=True)`
        # substitui a classe por uma nova, e a célula `__class__` que o `super()` de
        # zero argumentos usa ainda aponta para a original — `TypeError` na hora.
        _Pessoa.__post_init__(self)
        if self.nome is None:
            raise DadosInvalidosError(
                "Tomador: nome é obrigatório quando o tomador é identificado na DPS."
            )
