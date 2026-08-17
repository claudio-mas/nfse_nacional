"""CPF, CNPJ e os outros campos que dá para conferir sem rede.

P7 no `DESIGN.md`: validar localmente **só** o que é decidível offline. Dígito
verificador, quantidade de dígitos e formato entram; se o CNPJ existe na Receita, se
o município aderiu ao convênio, se a série pertence à faixa do emissor — não entram,
porque a resposta mora num servidor.

O ganho é concreto: um CPF com dígito errado custa uma viagem de ida e volta com
certificado, gzip e assinatura para voltar como `E0026`. Aqui custa uma exceção com
o nome do campo.

## CNPJ alfanumérico

A regra de 2026 permite CNPJ com letras nas 12 primeiras posições. **Os dois XSD
publicados não permitem**: `TSCNPJ` é `[0-9]{14}` tanto na 1.00 quanto na 1.01. Este
módulo segue o schema, porque é ele que a recepção aplica. Quando um ZIP novo
afrouxar o padrão, o teste que trava isso falha e avisa.
"""

from __future__ import annotations

from collections.abc import Sequence

from nfse_sefin.errors import DadosInvalidosError

__all__ = [
    "so_digitos",
    "validar_cpf",
    "validar_cnpj",
    "validar_codigo_municipio",
    "validar_cep",
    "validar_telefone",
    "validar_texto",
    "validar_texto_obrigatorio",
]


def so_digitos(valor: str) -> str:
    """Remove pontuação. `"01.761.135/0001-32"` vira `"01761135000132"`."""
    return "".join(c for c in valor if c.isdigit())


def _digito(base: str, pesos: Sequence[int]) -> str:
    """Dígito verificador módulo 11, comum a CPF e CNPJ."""
    soma = sum(int(d) * p for d, p in zip(base, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def validar_cpf(cpf: str, *, campo: str = "cpf") -> str:
    """Devolve o CPF com 11 dígitos, ou levanta `DadosInvalidosError`."""
    limpo = so_digitos(cpf)

    if len(limpo) != 11:
        raise DadosInvalidosError(f"{campo}: CPF tem 11 dígitos, recebi {len(limpo)} em {cpf!r}.")

    # Repetições como 111.111.111-11 passam no cálculo do dígito e são inválidas.
    if len(set(limpo)) == 1:
        raise DadosInvalidosError(f"{campo}: CPF com todos os dígitos iguais é inválido: {cpf!r}.")

    esperado = _digito(limpo[:9], list(range(10, 1, -1)))
    esperado += _digito(limpo[:10], list(range(11, 1, -1)))
    if limpo[9:] != esperado:
        raise DadosInvalidosError(f"{campo}: dígito verificador do CPF não confere em {cpf!r}.")

    return limpo


def validar_cnpj(cnpj: str, *, campo: str = "cnpj") -> str:
    """Devolve o CNPJ com 14 dígitos, ou levanta `DadosInvalidosError`."""
    limpo = so_digitos(cnpj)

    if len(limpo) != 14:
        raise DadosInvalidosError(f"{campo}: CNPJ tem 14 dígitos, recebi {len(limpo)} em {cnpj!r}.")

    if len(set(limpo)) == 1:
        raise DadosInvalidosError(
            f"{campo}: CNPJ com todos os dígitos iguais é inválido: {cnpj!r}."
        )

    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    esperado = _digito(limpo[:12], pesos)
    esperado += _digito(limpo[:13], [6, *pesos])
    if limpo[12:] != esperado:
        raise DadosInvalidosError(f"{campo}: dígito verificador do CNPJ não confere em {cnpj!r}.")

    return limpo


def validar_codigo_municipio(codigo: str, *, campo: str) -> str:
    """`TSCodMunIBGE` é `[0-9]{7}`. Sem zero à esquerda opcional, sem UF por extenso."""
    limpo = so_digitos(codigo)
    if len(limpo) != 7:
        raise DadosInvalidosError(
            f"{campo}: código IBGE de município tem 7 dígitos, recebi {codigo!r}. "
            "É o código do município, não o CEP nem a sigla da UF."
        )
    return limpo


def validar_cep(cep: str, *, campo: str = "cep") -> str:
    """`TSCEP` é `[0-9]{8}`."""
    limpo = so_digitos(cep)
    if len(limpo) != 8:
        raise DadosInvalidosError(f"{campo}: CEP tem 8 dígitos, recebi {cep!r}.")
    return limpo


def validar_telefone(valor: str | None, *, campo: str = "telefone") -> str | None:
    """`TSTelefone` é `[0-9]{6,20}`: só dígitos, sem parêntese, traço ou espaço."""
    if valor is None:
        return None
    limpo = so_digitos(valor)
    if not limpo:
        return None
    if not 6 <= len(limpo) <= 20:
        raise DadosInvalidosError(
            f"{campo}: o leiaute aceita de 6 a 20 dígitos, recebi {len(limpo)} em {valor!r}."
        )
    return limpo


def validar_texto(valor: str | None, campo: str, *, maximo: int) -> str | None:
    """Normaliza espaço e aplica as regras de `TSString`.

    `TSString` é `[!-ÿ]{1}[ -ÿ]{0,}[!-ÿ]{1}|[!-ÿ]{1}`: sem espaço nas pontas, e todo
    caractere entre `!` (0x21) e `ÿ` (0xFF). Acentuação portuguesa passa; travessão,
    aspas curvas e reticências de processador de texto **não**, e é exatamente o que
    vem colado de um documento do Word. Barato de conferir aqui, caro de descobrir
    pela rejeição.

    `xDescServ` é a exceção: usa `TSStringComQuebraDeLinha`, cujo padrão aceita
    qualquer caractere. Quem valida aquele campo não passa por aqui.
    """
    if valor is None:
        return None
    limpo = " ".join(valor.split())
    if not limpo:
        return None
    if len(limpo) > maximo:
        raise DadosInvalidosError(
            f"{campo}: o leiaute aceita no máximo {maximo} caracteres, recebi {len(limpo)}."
        )
    fora = sorted({c for c in limpo if not ("\x21" <= c <= "\xff" or c == " ")})
    if fora:
        raise DadosInvalidosError(
            f"{campo}: o leiaute só aceita caracteres de '!' a 'ÿ'; "
            f"estes estão fora: {''.join(fora)!r}."
        )
    return limpo


def validar_texto_obrigatorio(valor: str, campo: str, *, maximo: int) -> str:
    limpo = validar_texto(valor, campo, maximo=maximo)
    if limpo is None:
        raise DadosInvalidosError(f"{campo} é obrigatório e veio vazio.")
    return limpo
