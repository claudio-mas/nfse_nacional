"""Hierarquia de exceções.

Só a base e os erros de certificado por enquanto. `RejeicaoNFSe`,
`MunicipioNaoAderente`, `TransporteError` e `EventoRejeitado` entram junto com os
módulos que os levantam — ver "Ordem de release" no `DESIGN.md`.
"""

from __future__ import annotations

__all__ = [
    "NFSeError",
    "CertificadoError",
    "CertificadoIlegivelError",
    "CertificadoVencidoError",
]


class NFSeError(Exception):
    """Base de tudo que esta biblioteca levanta.

    Quem integra pode capturar só isto e ter certeza de que pegou tudo que é nosso,
    sem engolir `ValueError` de terceiros por acidente.
    """


class CertificadoError(NFSeError):
    """Problema com o certificado ICP-Brasil."""


class CertificadoIlegivelError(CertificadoError):
    """O arquivo `.pfx` não abriu.

    A causa quase sempre é senha errada. A outra causa possível é o arquivo usar
    cifras PKCS#12 legadas que a build local de OpenSSL recusa — e as duas produzem
    exatamente a mesma exceção lá embaixo (`Invalid password or PKCS12 data`), o que
    é o motivo de esta ser a dúvida de suporte mais comum de biblioteca fiscal
    brasileira.

    `usa_cifras_legadas` diz qual dos dois cenários é plausível para este arquivo.
    """

    def __init__(self, mensagem: str, *, usa_cifras_legadas: bool = False) -> None:
        super().__init__(mensagem)
        self.usa_cifras_legadas = usa_cifras_legadas


class CertificadoVencidoError(CertificadoError):
    """O certificado está fora do período de validade.

    Levantado só quando o chamador pede validação explícita. Carregar um certificado
    vencido é permitido de propósito: o `doctor` precisa conseguir abrir e relatar
    "venceu há 12 dias" em vez de estourar antes de conseguir dizer o que houve.
    """
