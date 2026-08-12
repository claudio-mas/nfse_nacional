"""Hierarquia de exceções.

Certificado e transporte por enquanto. `RejeicaoNFSe`, `MunicipioNaoAderente` e
`EventoRejeitado` entram junto com os módulos que os levantam — ver "Ordem de
release" no `DESIGN.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from nfse_sefin.catalogos.rejeicoes import Rejeicao, por_codigo

__all__ = [
    "NFSeError",
    "CertificadoError",
    "CertificadoIlegivelError",
    "CertificadoVencidoError",
    "MensagemSefin",
    "TransporteError",
    "RespostaInvalidaError",
    "MunicipioNaoAderente",
    "RejeicaoNFSe",
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


@dataclass(frozen=True, slots=True)
class MensagemSefin:
    """Uma mensagem do servidor, já normalizada.

    A SEFIN devolve erro em pelo menos quatro formatos diferentes, e os nomes das
    chaves variam de capitalização entre eles. Esta é a forma única para a qual tudo
    converge, para que quem integra leia um campo só.
    """

    codigo: str
    descricao: str
    complemento: str = ""

    def __str__(self) -> str:
        partes = [p for p in (self.codigo, self.descricao, self.complemento) if p]
        return " — ".join(partes) if partes else "(mensagem vazia)"


class TransporteError(NFSeError):
    """A requisição não terminou em resposta utilizável.

    Cobre erro de rede, timeout, e resposta HTTP com status de erro. `mensagens`
    traz o que o servidor disse, quando disse algo estruturado.

    Traduzir código `E####` para o texto oficial do anexo é trabalho de
    `RejeicaoNFSe`, que entra com o catálogo de rejeições. Aqui a mensagem sai como
    veio do servidor.
    """

    def __init__(
        self,
        mensagem: str,
        *,
        status_code: int | None = None,
        mensagens: Sequence[MensagemSefin] = (),
        corpo: str = "",
        metodo: str = "",
        url: str = "",
    ) -> None:
        super().__init__(mensagem)
        self.status_code = status_code
        self.mensagens: tuple[MensagemSefin, ...] = tuple(mensagens)
        self.corpo = corpo
        self.metodo = metodo
        self.url = url

    @property
    def codigos(self) -> tuple[str, ...]:
        """Só os códigos, na ordem em que vieram. Vazio quando o corpo não era JSON."""
        return tuple(m.codigo for m in self.mensagens if m.codigo)


class MunicipioNaoAderente(NFSeError):
    """O município não aderiu ao Sistema Nacional NFS-e.

    É o passo zero, não o passo três. "Obrigatório para todos os municípios desde
    janeiro de 2026" é meia-verdade: quem não aderir perde transferências voluntárias
    federais (LC 214/2025), mas a emissão não migrou toda — município com sistema
    próprio segue com `ambGer=1`. Tentar emitir contra um município não conveniado
    falha, e o erro que volta não diz que o problema é esse.
    """

    def __init__(self, codigo_municipio: str) -> None:
        super().__init__(
            f"Município {codigo_municipio} não aderiu ao Sistema Nacional NFS-e, "
            "ou não respondeu à consulta de convênio. Emitir contra ele vai falhar."
        )
        self.codigo_municipio = codigo_municipio


class RespostaInvalidaError(NFSeError):
    """O servidor respondeu 2xx, mas o corpo não tem a forma combinada.

    Separado de `TransporteError` de propósito: aqui a conversa funcionou e o
    contrato é que mudou. É o sintoma de a API ter sido alterada sem aviso, e merece
    investigação diferente de uma queda de rede.
    """


class RejeicaoNFSe(NFSeError):
    """A SEFIN recusou o documento por regra de negócio.

    A diferença para `TransporteError` é o que se pode fazer a seguir: transporte é
    problema de conexão ou de disponibilidade e às vezes passa na próxima tentativa;
    rejeição é decisão sobre o conteúdo, e repetir o mesmo XML devolve o mesmo erro.

    O valor está em `regras`: o código cru `E0014` vira o texto oficial do anexo e o
    caminho XML do campo culpado, sem o dev ter que abrir um documento de 373 KB.
    """

    def __init__(self, mensagens: Sequence[MensagemSefin], *, status_code: int | None = None):
        self.mensagens: tuple[MensagemSefin, ...] = tuple(mensagens)
        self.status_code = status_code
        self.regras: tuple[Rejeicao, ...] = tuple(
            regra for mensagem in self.mensagens for regra in por_codigo(mensagem.codigo)
        )
        super().__init__(self._descrever())

    def _descrever(self) -> str:
        if not self.mensagens:
            return "A SEFIN recusou o documento sem informar código."

        partes: list[str] = []
        for mensagem in self.mensagens:
            explicacoes = por_codigo(mensagem.codigo)
            if not explicacoes:
                # Código que o anexo não conhece. Melhor repetir o que o servidor
                # disse do que inventar significado.
                partes.append(str(mensagem))
                continue
            for regra in explicacoes:
                onde = f" em {regra.caminho_xml}{regra.campo or ''}" if regra.caminho_xml else ""
                partes.append(f"{regra.codigo}: {regra.mensagem}{onde}")
        return " | ".join(partes)

    @property
    def codigos(self) -> tuple[str, ...]:
        return tuple(m.codigo for m in self.mensagens if m.codigo)

    @property
    def caminhos_xml(self) -> tuple[str, ...]:
        """Campos culpados, para quem quer apontar o erro no formulário do ERP."""
        return tuple(f"{r.caminho_xml}{r.campo or ''}" for r in self.regras if r.caminho_xml)
